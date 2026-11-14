"""Load test runner for traffic scenarios with rigorous statistical accounting.

Supported scenarios:
1. steady                  - Constant low rate (real Groq on-demand service)
2. burst                   - Sudden concurrent traffic spike (stand-in simulator)
3. sustained_overload      - Sustained arrival rate exceeding capacity (stand-in simulator)
4. per_minute_limit_halved - Arrival rate with halving of RPM/TPM limits (stand-in simulator)
5. daily_budget_exhausted  - Arrivals when daily quota is depleted to zero (stand-in simulator)

Records:
- results.csv (preserving 12-column schema)
- experiments/logs/request_events.csv (companion event telemetry)
- experiments/logs/scenario_metadata.json (traceable scenario metadata)
"""
import asyncio
import os
import sys
import time
import json
from typing import Optional, List, Dict, Any
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from config import (
    DEFAULT_RETRIEVAL, get_groq_api_key, GROQ_MODEL, MODEL_PROFILES,
    PRICE_INPUT_PER_M, PRICE_OUTPUT_PER_M,
    SCENARIO_METADATA_JSON, SIMULATOR_DEFAULT_CONFIG, SIMULATOR_HALVED_CONFIG,
)
from indexer import PaperIndex
from llm_client import LLMClient
from rate_limiter import TokenBucketRateLimiter, RateLimiterConfig
from csv_logger import CSVLogger
from pipeline import Pipeline, PipelineResult
from questions import QUESTIONS
from simulator import run_simulator

INDEX_PATH = os.path.join(os.path.dirname(__file__), "paper_index.pkl")

# Representative answerable questions for load testing
LOAD_QUESTIONS = [q["question"] for q in QUESTIONS[:10]]

SCENARIOS = {
    "steady": {
        "num_requests": 5,
        "rate_per_minute": 10,
        "duration_s": 70,
        "use_simulator": False,
    },
    "burst": {
        "num_requests": 5,
        "rate_per_minute": 10,
        "duration_s": 24,
        "use_simulator": True,
        "burst_at": 2.0,
        "burst_count": 15,
    },
    "sustained_overload": {
        "num_requests": 25,
        "rate_per_minute": 120,
        "duration_s": 12,
        "use_simulator": True,
    },
    "per_minute_limit_halved": {
        "num_requests": 10,
        "rate_per_minute": 30,
        "duration_s": 41,
        "use_simulator": True,
        "rl_config": SIMULATOR_HALVED_CONFIG,
    },
    "daily_budget_exhausted": {
        "num_requests": 10,
        "rate_per_minute": 10,
        "duration_s": 54,
        "use_simulator": True,
        "pre_exhaust_daily": True,
    },
}


def clean_scenario_from_csv(csv_path: str, scenario_name: str):
    """Remove existing rows for a specific scenario before re-running to avoid duplicates."""
    import csv
    if not os.path.exists(csv_path):
        return
    with open(csv_path, "r", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = [r for r in reader if r.get("scenario") != scenario_name]
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


async def run_scenario(
    name: str,
    num_requests: int,
    rate_per_minute: float,
    duration_s: float,
    use_simulator: bool = True,
    rl_config: Optional[RateLimiterConfig] = None,
    burst_at: float = 0.0,
    burst_count: int = 0,
    pre_exhaust_daily: bool = False,
) -> Dict[str, Any]:
    """Run a load scenario and collect rigorously audited results."""
    idx = PaperIndex()
    if not os.path.exists(INDEX_PATH):
        idx.build(chunk_size=DEFAULT_RETRIEVAL.chunk_size, overlap=DEFAULT_RETRIEVAL.chunk_overlap)
        idx.save(INDEX_PATH)
    else:
        idx.load(INDEX_PATH)

    if use_simulator:
        run_simulator()

    source = "stand-in" if use_simulator else "real"
    api_key = None if not use_simulator else "sim-key"

    llm = LLMClient(use_simulator=use_simulator, api_key=api_key)
    rl_config = rl_config or (SIMULATOR_DEFAULT_CONFIG if use_simulator else MODEL_PROFILES.get(GROQ_MODEL, MODEL_PROFILES["qwen/qwen3.8-27b"]))
    rl = TokenBucketRateLimiter(rl_config)
    logger = CSVLogger()
    clean_scenario_from_csv(logger.path, name)
    clean_scenario_from_csv(logger.events_path, name)
    pipe = Pipeline(idx, llm, rl, logger)

    # Pre-exhaust daily budget completely if required by scenario
    if pre_exhaust_daily:
        rl._daily_requests = rl_config.rpd
        rl._daily_tokens = rl_config.tpd
        rl._save_quota_state()

    total_scheduled = num_requests + burst_count

    print(f"\n{'='*75}")
    print(f"Scenario: {name.upper()} ({source} provider, model: {rl_config.model_id})")
    print(f"  Scheduled: {total_scheduled} requests (Steady: {num_requests}, Burst: {burst_count})")
    print(f"  Nominal Rate: {rate_per_minute}/min | Duration target: {duration_s}s")
    print(f"  Rate Limiter Config: RPM={rl_config.rpm}, TPM={rl_config.tpm}, RPD={rl_config.rpd}")
    if burst_count > 0:
        print(f"  Burst Trigger: {burst_count} concurrent requests injected at t={burst_at:.1f}s")
    if pre_exhaust_daily:
        print(f"  Daily Budget: Exhausted (0 requests / 0 tokens remaining)")
    print(f"{'='*75}")

    tasks = []
    dispatch_times = []
    interval = (60.0 / rate_per_minute) if rate_per_minute > 0 else 0.1

    async def send_request(q_idx: int, delay_s: float):
        await asyncio.sleep(delay_s)
        t_dispatch = time.monotonic()
        dispatch_times.append(t_dispatch)
        question = LOAD_QUESTIONS[q_idx % len(LOAD_QUESTIONS)]
        result = await pipe.run(
            question=question,
            scenario=name,
            source=source,
            request_id=f"{name}-{q_idx:04d}",
        )
        return result

    # Schedule steady requests
    t_start = time.monotonic()
    for i in range(num_requests):
        delay = i * interval
        tasks.append(asyncio.create_task(send_request(i, delay)))

    # Schedule burst requests
    if burst_count > 0:
        for j in range(burst_count):
            b_idx = num_requests + j
            tasks.append(asyncio.create_task(send_request(b_idx, burst_at)))

    # Await all pipeline requests
    completed_results = await asyncio.gather(*tasks, return_exceptions=True)
    t_end = time.monotonic()
    total_experiment_duration_s = round(t_end - t_start, 1)

    # Calculate actual offered arrival rate from dispatch timeline
    if len(dispatch_times) > 1:
        dispatch_span_s = max(0.001, max(dispatch_times) - min(dispatch_times))
        if burst_count > 0 and num_requests == 0:
            offered_rate = round(len(dispatch_times) / dispatch_span_s * 60.0, 1)
        else:
            offered_rate = round(rate_per_minute, 1)
    else:
        offered_rate = round(rate_per_minute, 1)

    # Detailed accounting
    requests_sent = len(completed_results)
    succeeded_list: List[PipelineResult] = []
    rate_limited_count = 0
    timed_out_count = 0
    error_count = 0

    all_retries = []
    all_totals = []
    tokens_in_ok = []
    tokens_out_ok = []
    tokens_in_failed = []
    tokens_out_failed = []
    ttfts_ok = []
    totals_ok = []

    for r in completed_results:
        if isinstance(r, Exception):
            error_count += 1
            continue

        all_retries.append(r.retries)
        all_totals.append(r.total_ms)

        if r.status == "ok":
            succeeded_list.append(r)
            totals_ok.append(r.total_ms)
            tokens_in_ok.append(r.tokens_in)
            tokens_out_ok.append(r.tokens_out)
            if r.first_token_ms is not None and r.first_token_ms > 0:
                ttfts_ok.append(r.first_token_ms)
        elif r.status == "rate_limited":
            rate_limited_count += 1
            tokens_in_failed.append(r.tokens_in)
            tokens_out_failed.append(r.tokens_out)
        elif r.status == "timeout":
            timed_out_count += 1
            tokens_in_failed.append(r.tokens_in)
            tokens_out_failed.append(r.tokens_out)
        else:
            error_count += 1
            tokens_in_failed.append(r.tokens_in)
            tokens_out_failed.append(r.tokens_out)

    succeeded_count = len(succeeded_list)
    avg_retries = round(float(np.mean(all_retries)), 2) if all_retries else 0.0
    peak_queue = rl.peak_queue_length

    # Latency percentiles on consistent populations with explicit sample size N
    def calc_percentiles(arr: List[float]) -> Tuple[Optional[float], Optional[float], Optional[float], int]:
        if not arr:
            return None, None, None, 0
        p50 = round(float(np.percentile(arr, 50)), 1)
        p95 = round(float(np.percentile(arr, 95)), 1)
        p99 = round(float(np.percentile(arr, 99)), 1)
        return p50, p95, p99, len(arr)

    ttft_p50, ttft_p95, ttft_p99, n_ttft = calc_percentiles(ttfts_ok)
    tot_p50, tot_p95, tot_p99, n_tot = calc_percentiles(totals_ok if succeeded_count > 0 else all_totals)

    # Cost calculations separating input and output pricing
    # If 0 successful answers, Cost/1,000 successful answers is N/A!
    tokens_in_sum = sum(tokens_in_ok) + sum(tokens_in_failed)
    tokens_out_sum = sum(tokens_out_ok) + sum(tokens_out_failed)
    total_tokens_consumed = tokens_in_sum + tokens_out_sum

    if succeeded_count > 0:
        avg_in_ok = float(np.mean(tokens_in_ok))
        avg_out_ok = float(np.mean(tokens_out_ok))
        tokens_per_answer = int(avg_in_ok + avg_out_ok)
        cost_per_1000 = round(
            1000.0 * (
                avg_in_ok * (PRICE_INPUT_PER_M / 1_000_000.0)
                + avg_out_ok * (PRICE_OUTPUT_PER_M / 1_000_000.0)
            ),
            4
        )
        cost_per_1000_str = f"${cost_per_1000:.4f}"
    else:
        tokens_per_answer = 0
        cost_per_1000 = None
        cost_per_1000_str = "N/A"

    # Separate cost of successful attempts vs failed attempts
    cost_successful_total = (
        sum(tokens_in_ok) * (PRICE_INPUT_PER_M / 1_000_000.0)
        + sum(tokens_out_ok) * (PRICE_OUTPUT_PER_M / 1_000_000.0)
    )
    cost_failed_total = (
        sum(tokens_in_failed) * (PRICE_INPUT_PER_M / 1_000_000.0)
        + sum(tokens_out_failed) * (PRICE_OUTPUT_PER_M / 1_000_000.0)
    )
    cost_experiment_total = cost_successful_total + cost_failed_total

    summary = {
        "scenario": name,
        "source": source,
        "model_id": rl_config.model_id,
        "requests_scheduled": total_scheduled,
        "requests_sent": requests_sent,
        "requests_succeeded": succeeded_count,
        "requests_rate_limited": rate_limited_count,
        "requests_timed_out": timed_out_count,
        "requests_abandoned": error_count,
        "duration_s": total_experiment_duration_s,
        "offered_rate_per_min": offered_rate,
        "succeeded_pct": round(100.0 * succeeded_count / requests_sent, 1),
        "rate_limited_pct": round(100.0 * rate_limited_count / requests_sent, 1),
        "timed_out_pct": round(100.0 * timed_out_count / requests_sent, 1),
        "retries_per_request": avg_retries,
        "peak_queue_length": peak_queue,
        "tokens_per_answer": tokens_per_answer,
        "total_tokens_consumed": total_tokens_consumed,
        "cost_per_1000": cost_per_1000,
        "cost_per_1000_str": cost_per_1000_str,
        "cost_successful_total": round(cost_successful_total, 6),
        "cost_failed_total": round(cost_failed_total, 6),
        "cost_experiment_total": round(cost_experiment_total, 6),
        "ttft_p50": ttft_p50,
        "ttft_p95": ttft_p95,
        "ttft_p99": ttft_p99,
        "ttft_sample_size": n_ttft,
        "total_p50": tot_p50,
        "total_p95": tot_p95,
        "total_p99": tot_p99,
        "total_sample_size": n_tot,
    }

    print(f"\n--- Scenario Summary: {name} ---")
    print(f"  Duration: {total_experiment_duration_s}s | Offered Rate: {offered_rate}/min")
    print(f"  Sent: {requests_sent} | Succeeded: {succeeded_count} ({summary['succeeded_pct']}%) | "
          f"Rate-limited: {rate_limited_count} ({summary['rate_limited_pct']}%) | "
          f"Timed-out: {timed_out_count} ({summary['timed_out_pct']}%)")
    print(f"  Peak Queue Depth: {peak_queue} | Retries/req: {avg_retries}")
    print(f"  Tokens/Answer: {tokens_per_answer} | Cost/1,000 Answers: {cost_per_1000_str}")
    if ttft_p50 is not None:
        print(f"  TTFT p50/p95/p99 (N={n_ttft}): {ttft_p50} / {ttft_p95} / {ttft_p99} ms")
    else:
        print(f"  TTFT p50/p95/p99: not measured (N=0 successful token generations)")
    print(f"  Total p50/p95/p99 (N={n_tot}): {tot_p50} / {tot_p95} / {tot_p99} ms")

    await llm.close()

    # Save to scenario metadata
    _update_scenario_metadata(summary)

    return summary


def _update_scenario_metadata(summary: Dict[str, Any], meta_path: str = SCENARIO_METADATA_JSON):
    """Update experiments/logs/scenario_metadata.json with traceable scenario data in a consistent dictionary format."""
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
    existing: Dict[str, Any] = {}
    if os.path.exists(meta_path):
        try:
            with open(meta_path, "r") as f:
                raw = json.load(f)
                if isinstance(raw, list):
                    for item in raw:
                        if isinstance(item, dict) and "scenario" in item:
                            existing[item["scenario"]] = item
                elif isinstance(raw, dict):
                    existing = raw
        except Exception:
            existing = {}

    existing[summary["scenario"]] = summary
    with open(meta_path, "w") as f:
        json.dump(existing, f, indent=2)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="The Relay - Load Test Runner")
    parser.add_argument("--scenario", choices=list(SCENARIOS.keys()) + ["all"], default="all",
                        help="Scenario to run ('steady', 'burst', 'sustained_overload', 'per_minute_limit_halved', 'daily_budget_exhausted', or 'all')")
    args = parser.parse_args()

    async def _run():
        if args.scenario == "all":
            for sc_name, sc_params in SCENARIOS.items():
                await run_scenario(name=sc_name, **sc_params)
        else:
            await run_scenario(name=args.scenario, **SCENARIOS[args.scenario])

    asyncio.run(_run())


if __name__ == "__main__":
    main()
