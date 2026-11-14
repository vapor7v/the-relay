"""Retrieval evaluation runner across three configurations using the frozen 18-question suite.

Evaluates:
1. small-5-no   (500 char chunk, 5 pieces fetched, no re-ranking)
2. medium-3-no  (1000 char chunk, 3 pieces fetched, no re-ranking)
3. medium-5-yes (1000 char chunk, 5 pieces fetched, LLM re-ranking)

Outputs:
- results.csv (genuine request records for all 54 questions)
- experiments/reports/retrieval_evaluation_details.json (claim-by-claim evaluation)
- relay/retrieval_summary.json (summary metrics for Table 3)
"""
import asyncio
import os
import sys
import json
import argparse
import csv
from typing import Dict, Any, List, Tuple, Optional
import numpy as np

sys.path.insert(0, os.path.dirname(__file__))

from config import (
    RETRIEVAL_SETTINGS, RetrievalSetting,
    RETRIEVAL_DETAILS_JSON, RESULTS_CSV,
    RateLimiterConfig, MODEL_PROFILES, GROQ_MODEL,
)
from indexer import PaperIndex
from llm_client import LLMClient
from rate_limiter import TokenBucketRateLimiter
from csv_logger import CSVLogger
from pipeline import Pipeline, PipelineResult
from questions import QUESTIONS
from simulator import run_simulator


def clean_scenario_from_csv(csv_path: str, scenario_name: str):
    """Remove existing rows for a specific scenario before re-running."""
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


async def evaluate_retrieval_suite(
    use_simulator: bool = False,
    persist_to_results_csv: bool = True,
    delay_between_requests: float = 2.0,
    target_setting_name: Optional[str] = None,
):
    """Run retrieval evaluation across three configurations."""
    if use_simulator:
        run_simulator(seed=42)
        from simulator import _global_state
        if _global_state:
            _global_state.cal["rpm_limit"] = 500
            _global_state.cal["tpm_limit"] = 1000000
            _global_state.cal["failure_rate"] = 0.0

    summary_list = []
    # Load existing evaluation details if present
    all_evaluation_details: Dict[str, List[Dict[str, Any]]] = {}
    if os.path.exists(RETRIEVAL_DETAILS_JSON):
        try:
            with open(RETRIEVAL_DETAILS_JSON, "r") as f:
                all_evaluation_details = json.load(f)
        except Exception:
            all_evaluation_details = {}

    settings_to_run = [
        s for s in RETRIEVAL_SETTINGS
        if target_setting_name is None or s.name == target_setting_name
    ]

    source = "stand-in" if use_simulator else "real"
    api_key = "sim-key" if use_simulator else None

    target_csv = RESULTS_CSV if persist_to_results_csv else os.path.join(
        os.path.dirname(__file__), "..", "scratch", "eval_temp.csv"
    )
    logger = CSVLogger(path=target_csv)

    for setting in settings_to_run:
        scenario_name = f"retrieval_eval_{setting.name}"
        if persist_to_results_csv:
            clean_scenario_from_csv(target_csv, scenario_name)

        idx_path = os.path.join(os.path.dirname(__file__), f"paper_index_{setting.name}.pkl")
        if not os.path.exists(idx_path):
            idx_path = os.path.join(os.path.dirname(__file__), "paper_index.pkl")

        idx = PaperIndex()
        idx.load(idx_path)

        llm = LLMClient(use_simulator=use_simulator, api_key=api_key)
        rl_config = RateLimiterConfig(rpm=30, tpm=8000, itpm=7000, rpd=1000, tpd=200000)
        rl = TokenBucketRateLimiter(rl_config)
        pipe = Pipeline(idx, llm, rl, logger, retrieval_setting=setting)

        print(f"\n{'='*75}")
        print(f"Evaluating Retrieval Configuration: {setting.name} ({source} provider)")
        print(f"Chunk size: {setting.chunk_size} chars | Top-k: {setting.top_k} | Re-rank: {setting.rerank}")
        print(f"{'='*75}")

        records: List[Tuple[Dict[str, Any], PipelineResult]] = []
        setting_eval_details: List[Dict[str, Any]] = []

        for q in QUESTIONS:
            res = await pipe.run(
                question=q["question"],
                scenario=scenario_name,
                source=source,
                request_id=f"ret-{setting.name}-{q['id']}",
            )
            records.append((q, res))

            details = res.evaluation_details or {}
            # Determine diagnosed failure origin
            failure_origin = "N/A (Correct or Correctly Refused)"
            if res.answer_grade == "wrong":
                if q.get("expected_paper") and not any(q["expected_paper"] in c.lower() for c in res.retrieved_chunk_labels):
                    failure_origin = "1. Retrieval (Target paper passages not retrieved in top-k)"
                elif not res.retrieved_chunk_labels:
                    failure_origin = "1. Retrieval (Zero chunks retrieved)"
                elif not details.get("generated_citations"):
                    failure_origin = "3. Answer Generation (Model omitted primary citations)"
                elif not res.verification_passed:
                    failure_origin = "4. Citation Verification (Draft withheld or failed verification)"
                else:
                    failure_origin = "2. Evidence Selection (Retrieved chunk lacked specific quantitative fact)"
            elif res.answer_grade == "refused_wrongly":
                failure_origin = "1. Retrieval (Relevant passages missed, triggering query refusal)"

            q_detail = {
                "question_id": q["id"],
                "question": q["question"],
                "expected_paper": q.get("expected_paper"),
                "expected_grade": q.get("expected_grade"),
                "retrieved_passage_ids": res.retrieved_chunk_labels,
                "expected_facts": [c.get("claim") for c in q.get("required_claims", [])],
                "generated_answer": res.answer,
                "generated_citations": details.get("generated_citations", []),
                "claims_evaluated": details.get("claims_evaluated", []),
                "final_grade": res.answer_grade,
                "failure_reason": details.get("failure_reason", ""),
                "diagnosed_failure_origin": failure_origin,
            }
            setting_eval_details.append(q_detail)

            ft_str = f"{res.first_token_ms:.1f}ms" if res.first_token_ms is not None else "null"
            status_symbol = "✓" if res.answer_grade == q["expected_grade"] else "✗"
            print(f"  {status_symbol} [{q['id']}] Grade: {res.answer_grade:<17} "
                  f"TTFT: {ft_str:<10} Total: {res.total_ms:.1f}ms | Tokens: {res.tokens_in}in/{res.tokens_out}out")

            # Pacing delay between questions to stay smoothly below 30 RPM
            if delay_between_requests > 0:
                await asyncio.sleep(delay_between_requests)

        await llm.close()
        all_evaluation_details[setting.name] = setting_eval_details

        # Summary statistics
        total_q = len(records)
        correct_cited = sum(1 for q, r in records if r.answer_grade == "correct")
        wrong = sum(1 for q, r in records if r.answer_grade == "wrong")
        refused_correctly = sum(1 for q, r in records if r.answer_grade == "refused_correctly")
        refused_wrongly = sum(1 for q, r in records if r.answer_grade == "refused_wrongly")

        ttfts = [r.first_token_ms for q, r in records if (r.first_token_ms is not None and r.first_token_ms > 0)]
        totals = [r.total_ms for q, r in records if r.total_ms > 0]
        tokens_per_ans = [r.tokens_in + r.tokens_out for q, r in records]

        summary = {
            "setting": setting.name,
            "chunk_size": setting.chunk_size,
            "top_k": setting.top_k,
            "rerank": "yes" if setting.rerank else "no",
            "questions_asked": total_q,
            "correct_cited_pct": round(100.0 * correct_cited / total_q, 1),
            "wrong_pct": round(100.0 * wrong / total_q, 1),
            "refused_correctly_pct": round(100.0 * refused_correctly / total_q, 1),
            "refused_wrongly_pct": round(100.0 * refused_wrongly / total_q, 1),
            "tokens_per_answer": int(np.mean(tokens_per_ans)),
            "ttft_p50": round(float(np.percentile(ttfts, 50)), 1) if ttfts else 0.0,
            "ttft_p95": round(float(np.percentile(ttfts, 95)), 1) if ttfts else 0.0,
            "total_p50": round(float(np.percentile(totals, 50)), 1) if totals else 0.0,
            "total_p95": round(float(np.percentile(totals, 95)), 1) if totals else 0.0,
        }
        summary_list.append(summary)

    # Save detailed evaluation artifact
    os.makedirs(os.path.dirname(RETRIEVAL_DETAILS_JSON), exist_ok=True)
    with open(RETRIEVAL_DETAILS_JSON, "w") as f:
        json.dump(all_evaluation_details, f, indent=2)
    print(f"\nSaved detailed claim-by-claim evaluation to {RETRIEVAL_DETAILS_JSON}")

    # Save summary
    out_path = os.path.join(os.path.dirname(__file__), "retrieval_summary.json")
    with open(out_path, "w") as f:
        json.dump(summary_list, f, indent=2)
    print(f"Saved retrieval summary to {out_path}")

    # Display Table 3
    print("\n" + "=" * 115)
    print("Table 3: Retrieval settings (at least three)")
    print("=" * 115)
    print(f"{'Setting':<25} | {'Questions':<9} | {'Correct%':<8} | {'Wrong%':<6} | {'Refused%':<8} | {'Tokens/Ans':<10} | {'TTFT p50/p95 (ms)':<20} | {'Total p50/p95 (ms)':<20}")
    print("-" * 115)
    for s in summary_list:
        lbl = f"{s['chunk_size']}ch, {s['top_k']}pcs, {s['rerank']}"
        ttft_str = f"{s['ttft_p50']} / {s['ttft_p95']}"
        tot_str = f"{s['total_p50']} / {s['total_p95']}"
        print(f"{lbl:<25} | {s['questions_asked']:<9} | {s['correct_cited_pct']:<8} | {s['wrong_pct']:<6} | {s['refused_correctly_pct']:<8} | {s['tokens_per_answer']:<10} | {ttft_str:<20} | {tot_str:<20}")

    return summary_list


def main():
    parser = argparse.ArgumentParser(description="The Relay - Retrieval Evaluation Runner")
    parser.add_argument("--simulator", action="store_true", help="Run using stand-in simulator instead of real Groq API")
    parser.add_argument("--setting", choices=["small-5-no", "medium-3-no", "medium-5-yes"], default=None,
                        help="Specific setting to evaluate (default: all 3)")
    parser.add_argument("--delay", type=float, default=2.0, help="Pacing delay between requests in seconds")
    parser.add_argument("--no-persist", action="store_true", help="Do not persist results to results.csv")
    args = parser.parse_args()

    asyncio.run(evaluate_retrieval_suite(
        use_simulator=args.simulator,
        persist_to_results_csv=not args.no_persist,
        delay_between_requests=args.delay,
        target_setting_name=args.setting,
    ))


if __name__ == "__main__":
    main()
