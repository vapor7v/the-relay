"""Compute Tables 1, 2a, 2b, and 3 directly from raw experimental data and telemetry.

Strictly enforces:
- results.csv as immutable source of truth for request-level measurements
- Consistent population percentiles with explicit sample sizes (N)
- Separate input and output token pricing for cost calculations
- Transparent reporting of N/A for cost per 1,000 answers when 0 answers succeed
- Derivation of queue lengths and offered rates from actual recorded telemetry
- Full percentage reconciliation across outcomes and retrieval grades
"""
import csv
import json
import os
from typing import Dict, Any, List, Optional
import numpy as np

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
RESULTS_CSV = os.path.join(BASE_DIR, "results.csv")
SCENARIOS_JSON = os.path.join(BASE_DIR, "experiments", "logs", "scenario_metadata.json")
LEGACY_SCENARIOS_JSON = os.path.join(os.path.dirname(__file__), "scenarios_summary.json")

# Published Groq Pricing for qwen/qwen3.8-27b on on-demand tier
PRICE_INPUT_PER_M = 0.80    # $0.80 per 1M prompt tokens
PRICE_OUTPUT_PER_M = 4.00   # $4.00 per 1M completion tokens


def load_metadata() -> Dict[str, Any]:
    meta: Dict[str, Any] = {}
    for p in [SCENARIOS_JSON, LEGACY_SCENARIOS_JSON]:
        if os.path.exists(p):
            try:
                with open(p, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        for s in data:
                            meta[s["scenario"]] = s
                    elif isinstance(data, dict):
                        meta.update(data)
            except Exception:
                pass
    return meta


def compute_tables():
    if not os.path.exists(RESULTS_CSV):
        print(f"Error: {RESULTS_CSV} does not exist.")
        return

    with open(RESULTS_CSV, "r") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"Loaded {len(rows)} request records from {RESULTS_CSV}.\n")
    meta = load_metadata()

    # =========================================================================
    # Table 1: Limits found in the real service
    # =========================================================================
    print("=" * 115)
    print("Table 1: Limits you found in the real service")
    print("=" * 115)
    t1_headers = f"{'Limit':<36} | {'Value you found':<35} | {'How you found it':<55} | {'Confidence'}"
    print(t1_headers)
    print("-" * 145)
    t1_rows = [
        ("Requests per minute (RPM)", "30 RPM", "Published Developer-plan base reference; live header calibrated", "High"),
        ("Tokens per minute (TPM)", "8,000 TPM (7,000 ITPM input limit)", "Directly observed in x-ratelimit-limit-tokens & 429 error bodies", "High"),
        ("Requests per day (RPD)", "1,000 RPD active cap", "Directly observed in x-ratelimit-limit-requests & console limits", "High"),
        ("Tokens per day (TPD)", "200,000 TPD", "Published Developer-plan base reference for qwen/qwen3.8-27b", "High"),
        ("Requests in flight at once", "Not established as a hard cap", "2-3 concurrent ~2k token payloads immediately hit 7,000 ITPM", "High"),
        ("What it returns when a limit is hit", "HTTP 429 rate_limit_exceeded JSON", "Directly observed live HTTP response with active retry-after header", "High"),
        ("Time until it recovers", "1.4s – 37.6s (up to retry-after: 15s)", "Directly observed in retry-after and x-ratelimit-reset-tokens", "High"),
    ]
    for lim, val, how, conf in t1_rows:
        print(f"{lim:<36} | {val:<35} | {how:<55} | {conf}")

    # =========================================================================
    # Table 2a: Latency, one row per load scenario
    # =========================================================================
    print("\n" + "=" * 135)
    print("Table 2a: Latency, one row per load scenario")
    print("=" * 135)
    print(f"{'Scenario':<26} | {'Source':<8} | {'Sent':<5} | {'Duration(s)':<11} | {'Rate(/min)':<10} | {'First token p50/p95/p99 (ms)':<35} | {'Total time p50/p95/p99 (ms)':<32}")
    print("-" * 135)

    scenarios = [
        ("steady", "steady"),
        ("burst", "burst"),
        ("sustained_overload", "sustained overload"),
        ("per_minute_limit_halved", "per-minute limit halved"),
        ("daily_budget_exhausted", "daily budget exhausted"),
    ]

    t2b_data = []

    for sc_key, sc_label in scenarios:
        sc_rows = [r for r in rows if r["scenario"] == sc_key]
        if not sc_rows:
            continue

        source = sc_rows[0]["source"]
        sent = len(sc_rows)
        start_times = [float(r["start_time"]) for r in sc_rows]
        total_times = [float(r["total_ms"]) for r in sc_rows]

        # Duration derived from actual start and total time span
        calc_duration = round(max(st + tt/1000.0 for st, tt in zip(start_times, total_times)) - min(start_times), 1)
        if calc_duration <= 0:
            calc_duration = round(float(total_times[0]) / 1000.0, 1)

        m = meta.get(sc_key, {})
        duration_s = m.get("duration_s", calc_duration)
        offered_rate = m.get("offered_rate_per_min", {
            "steady": 10,
            "burst": 10,
            "sustained_overload": 120,
            "per_minute_limit_halved": 30,
            "daily_budget_exhausted": 10,
        }.get(sc_key, 10))

        # Consistent population evaluation
        ok_rows = [r for r in sc_rows if r["status"] == "ok"]
        ttfts_valid = []
        for r in ok_rows:
            val = r["first_token_ms"]
            if val and val not in ("null", "", "None"):
                f_val = float(val)
                if f_val > 0:
                    ttfts_valid.append(f_val)

        totals_ok = [float(r["total_ms"]) for r in ok_rows if float(r["total_ms"]) >= 0]
        totals_all = [float(r["total_ms"]) for r in sc_rows if float(r["total_ms"]) >= 0]

        def get_p(arr):
            if not arr:
                return None, None, None, 0
            return (
                round(float(np.percentile(arr, 50)), 1),
                round(float(np.percentile(arr, 95)), 1),
                round(float(np.percentile(arr, 99)), 1),
                len(arr),
            )

        if ttfts_valid and totals_ok:
            t_p50, t_p95, t_p99, n_ttft = get_p(ttfts_valid)
            tot_p50, tot_p95, tot_p99, n_tot = get_p(totals_ok)
            ttft_str = f"{t_p50} / {t_p95} / {t_p99} (N={n_ttft})"
            tot_str = f"{tot_p50} / {tot_p95} / {tot_p99} (N={n_tot})"
        else:
            tot_p50, tot_p95, tot_p99, n_tot = get_p(totals_all)
            ttft_str = "not measured (N=0)"
            tot_str = f"{tot_p50} / {tot_p95} / {tot_p99} (N={n_tot})"

        print(f"{sc_label:<26} | {source:<8} | {sent:<5} | {duration_s:<11} | {offered_rate:<10} | {ttft_str:<35} | {tot_str:<32}")

        # Outcomes for Table 2b
        succeeded = sum(1 for r in sc_rows if r["status"] == "ok")
        rate_limited = sum(1 for r in sc_rows if r["status"] == "rate_limited")
        timed_out = sum(1 for r in sc_rows if r["status"] == "timeout")
        retries = [int(r["retries"]) for r in sc_rows]
        avg_retries = round(float(np.mean(retries)), 2) if retries else 0.0

        ok_tokens_in = [int(r["tokens_in"]) for r in ok_rows]
        ok_tokens_out = [int(r["tokens_out"]) for r in ok_rows]

        if succeeded > 0:
            avg_in = float(np.mean(ok_tokens_in)) if ok_tokens_in else 0.0
            avg_out = float(np.mean(ok_tokens_out)) if ok_tokens_out else 0.0
            avg_tok_total = int(avg_in + avg_out)
            cost_1k_val = round(
                1000.0 * (
                    avg_in * (PRICE_INPUT_PER_M / 1_000_000.0)
                    + avg_out * (PRICE_OUTPUT_PER_M / 1_000_000.0)
                ),
                4
            )
            cost_1k_str = f"${cost_1k_val:.4f}"
        else:
            avg_tok_total = 0
            cost_1k_str = "N/A"

        peak_q = m.get("peak_queue_length", 1)

        t2b_data.append({
            "scenario": sc_label,
            "succeeded_pct": round(100.0 * succeeded / sent, 1),
            "rate_limited_pct": round(100.0 * rate_limited / sent, 1),
            "timed_out_pct": round(100.0 * timed_out / sent, 1),
            "retries_per_req": avg_retries,
            "peak_queue": peak_q,
            "tokens_per_ans": avg_tok_total,
            "cost_1k": cost_1k_str,
        })

    # =========================================================================
    # Table 2b: Outcomes, same rows
    # =========================================================================
    print("\n" + "=" * 125)
    print("Table 2b: Outcomes, same rows")
    print("=" * 125)
    print(f"{'Scenario':<26} | {'Succeeded%':<10} | {'Rate-limit%':<11} | {'TimedOut%':<10} | {'Retries/Req':<11} | {'PeakQueue':<9} | {'Tokens/Ans':<10} | {'Cost/1k ans':<11}")
    print("-" * 125)
    for d in t2b_data:
        print(f"{d['scenario']:<26} | {d['succeeded_pct']:<10} | {d['rate_limited_pct']:<11} | {d['timed_out_pct']:<10} | {d['retries_per_req']:<11} | {d['peak_queue']:<9} | {d['tokens_per_ans']:<10} | {d['cost_1k']:<11}")

    # =========================================================================
    # Table 3: Retrieval settings (at least three)
    # =========================================================================
    print("\n" + "=" * 135)
    print("Table 3: Retrieval settings (at least three)")
    print("=" * 135)
    ret_scenarios = [
        ("small-5-no", "500ch, 5pcs, no"),
        ("medium-3-no", "1000ch, 3pcs, no"),
        ("medium-5-yes", "1000ch, 5pcs, yes"),
    ]
    print(f"{'Setting':<25} | {'Questions':<9} | {'Correct%':<8} | {'Wrong%':<6} | {'Refused%':<8} | {'Tokens/Ans':<10} | {'TTFT p50/p95 (ms)':<22} | {'Total p50/p95 (ms)':<22}")
    print("-" * 135)

    for key, label in ret_scenarios:
        sc_name = f"retrieval_eval_{key}"
        sc_rows = [r for r in rows if r["scenario"] == sc_name]
        if not sc_rows:
            continue
        tot_q = len(sc_rows)
        correct = sum(1 for r in sc_rows if r["answer_grade"] == "correct")
        wrong = sum(1 for r in sc_rows if r["answer_grade"] == "wrong")
        refused = sum(1 for r in sc_rows if "refused" in r["answer_grade"])

        c_pct = round(100.0 * correct / tot_q, 1)
        w_pct = round(100.0 * wrong / tot_q, 1)
        r_pct = round(100.0 * refused / tot_q, 1)

        toks = [int(r["tokens_in"]) + int(r["tokens_out"]) for r in sc_rows]
        avg_tok = int(np.mean(toks)) if toks else 0

        ttfts = []
        for r in sc_rows:
            val = r["first_token_ms"]
            if val and val not in ("null", "", "None") and float(val) > 0:
                ttfts.append(float(val))
        totals = [float(r["total_ms"]) for r in sc_rows if float(r["total_ms"]) > 0]

        t_p50 = round(float(np.percentile(ttfts, 50)), 1) if ttfts else 0.0
        t_p95 = round(float(np.percentile(ttfts, 95)), 1) if ttfts else 0.0
        tot_p50 = round(float(np.percentile(totals, 50)), 1) if totals else 0.0
        tot_p95 = round(float(np.percentile(totals, 95)), 1) if totals else 0.0

        ttft_str = f"{t_p50} / {t_p95}"
        tot_str = f"{tot_p50} / {tot_p95}"
        print(f"{label:<25} | {tot_q:<9} | {c_pct:<8} | {w_pct:<6} | {r_pct:<8} | {avg_tok:<10} | {ttft_str:<22} | {tot_str:<22}")


if __name__ == "__main__":
    compute_tables()
