"""Evaluates the improved hybrid RAG pipeline on the frozen 18-question suite using real Groq.

Pipeline Architecture:
- Section-aware document chunking (EnhancedChunk)
- Hybrid retrieval: BM25Okapi + TF-IDF + Dense MiniLM embeddings (RRF, k=60)
- Local candidate reranking: entity, number, section heading, paper alignment boosts
- Evidence-first drafting prompt
- Tailored claim-level citation verification judge

Outputs:
- experiments/reports/retrieval_evaluation_improved.json (claim-by-claim details)
- experiments/reports/results_improved_hybrid.csv (telemetry records)
- experiments/reports/retrieval_improved_summary.json (aggregate metrics)
"""
import os
import sys
import time
import json
import asyncio
import csv
from typing import Dict, Any, List

# Ensure offline embeddings model loading
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chunker import build_corpus
from hybrid_retriever import HybridRetriever
from reranker import LocalCandidateReranker
from llm_client import LLMClient
from rate_limiter import TokenBucketRateLimiter
from config import MODEL_PROFILES, GROQ_MODEL, RetrievalSetting, RateLimiterConfig
from csv_logger import CSVLogger
from pipeline import Pipeline, PipelineResult
from questions import QUESTIONS


async def wait_for_capacity(rl: TokenBucketRateLimiter, min_tokens: float = 5000.0):
    """Wait until token bucket has enough capacity before launching request."""
    rl._refill()
    while rl._itpm_tokens < min_tokens or rl._tpm_tokens < min_tokens:
        needed = max(min_tokens - rl._itpm_tokens, min_tokens - rl._tpm_tokens)
        refill_rate = rl.config.tpm / 60.0
        wait_s = min(35.0, max(2.0, needed / refill_rate))
        print(f"  [Pacing] Available tokens: {rl._itpm_tokens:.0f}/{min_tokens:.0f}. Waiting {wait_s:.1f}s for bucket refill...")
        await asyncio.sleep(wait_s)
        rl._refill()


async def run_improved_suite(use_simulator: bool = False):
    source = "stand-in" if use_simulator else "real"
    api_key = "sim-key" if use_simulator else None
    
    if use_simulator:
        from simulator import run_simulator, _global_state
        run_simulator(seed=42)
        from simulator import _global_state
        if _global_state:
            _global_state.cal["rpm_limit"] = 500
            _global_state.cal["tpm_limit"] = 1000000
            _global_state.cal["failure_rate"] = 0.0

    print("=" * 75)
    print(f"THE RELAY — IMPROVED HYBRID RAG EVALUATION ({source.upper()})")
    print(f"Model: {GROQ_MODEL}")
    print("Target: 90%+ answer accuracy (>=14/15 correct) + 100% correct refusals (3/3)")
    print("=" * 75)

    # 1. Build corpus and initialize hybrid retriever
    print("Loading section-aware corpus...")
    chunks = build_corpus("section_aware")
    cache_path = os.path.join(os.path.dirname(__file__), "paper_embeddings_section_aware.pkl")
    print(f"Corpus size: {len(chunks)} chunks. Loading embeddings from cache: {cache_path}")
    
    retriever = HybridRetriever(chunks, enable_dense=True, embedding_cache_path=cache_path)
    reranker = LocalCandidateReranker()

    # 2. Setup LLM client, Rate Limiter, and Logger
    llm = LLMClient(use_simulator=use_simulator, api_key=api_key)
    rl_config = RateLimiterConfig(rpm=500, tpm=1000000, rpd=10000, tpd=2000000) if use_simulator else MODEL_PROFILES[GROQ_MODEL]
    rl = TokenBucketRateLimiter(rl_config)

    reports_dir = os.path.join(os.path.dirname(__file__), "..", "experiments", "reports")
    os.makedirs(reports_dir, exist_ok=True)
    csv_filename = "results_improved_hybrid_sim.csv" if use_simulator else "results_improved_hybrid.csv"
    csv_path = os.path.join(reports_dir, csv_filename)
    
    # Initialize fresh CSV with required schema
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "request_id", "scenario", "source", "start_time",
            "first_token_ms", "total_ms", "status", "retries",
            "tokens_in", "tokens_out", "retrieval_setting", "answer_grade"
        ])

    logger = CSVLogger(path=csv_path)

    improved_setting = RetrievalSetting(
        name="hybrid-rrf-rerank",
        chunk_size=700,
        chunk_overlap=100,
        top_k=5,
        rerank=True,
    )

    pipe = Pipeline(
        index=retriever,
        llm=llm,
        rate_limiter=rl,
        csv_logger=logger,
        retrieval_setting=improved_setting,
        reranker=reranker,
    )

    results_details: List[Dict[str, Any]] = []
    summary_counts = {"correct": 0, "wrong": 0, "refused_correctly": 0, "refused_wrongly": 0}
    total_tokens_in = 0
    total_tokens_out = 0
    latencies = []
    ttfts = []

    details_filename = "retrieval_evaluation_improved_sim.json" if use_simulator else "retrieval_evaluation_improved.json"
    details_path = os.path.join(reports_dir, details_filename)

    for i, q in enumerate(QUESTIONS, 1):
        qid = q["id"]
        q_text = q["question"]
        exp_grade = q["expected_grade"]
        print(f"\n[{i}/{len(QUESTIONS)}] Processing {qid}: \"{q_text[:50]}...\"")
        print(f"  Expected Grade: {exp_grade}")

        # Check capacity before running
        if not use_simulator:
            min_tokens_needed = 800.0 if exp_grade == "refused_correctly" else 5200.0
            await wait_for_capacity(rl, min_tokens=min_tokens_needed)
        else:
            await asyncio.sleep(0.1)

        t0 = time.monotonic()
        res: PipelineResult = await pipe.run(
            question=q_text,
            scenario="retrieval_eval_improved_hybrid",
            source=source,
            request_id=f"improved-{qid}",
        )
        duration = time.monotonic() - t0

        grade = res.answer_grade
        summary_counts[grade] = summary_counts.get(grade, 0) + 1
        total_tokens_in += res.tokens_in
        total_tokens_out += res.tokens_out
        latencies.append(res.total_ms)
        if res.first_token_ms:
            ttfts.append(res.first_token_ms)

        print(f"  Status: {res.status} | Grade: {grade.upper()} | Verified: {res.verification_passed} | Duration: {duration:.2f}s")
        print(f"  Answer: {res.answer[:120]}...")
        if res.evaluation_details and res.evaluation_details.get("failure_reason"):
            print(f"  Failure Reason: {res.evaluation_details.get('failure_reason')}")

        eval_entry = res.evaluation_details or {
            "question_id": qid,
            "question": q_text,
            "final_grade": grade,
            "generated_answer": res.answer,
        }
        results_details.append(eval_entry)

        # Immediate checkpoint save after each question
        with open(details_path, "w", encoding="utf-8") as f:
            json.dump({
                "model": GROQ_MODEL,
                "completed_so_far": len(results_details),
                "summary_counts": summary_counts,
                "evaluations": results_details,
            }, f, indent=2)

    # Compute final summary percentages
    ans_correct = summary_counts["correct"]
    ans_wrong = summary_counts["wrong"]
    ref_correct = summary_counts["refused_correctly"]
    ref_wrong = summary_counts["refused_wrongly"]

    pct_correct = (ans_correct / 18) * 100
    pct_wrong = (ans_wrong / 18) * 100
    pct_ref_correct = (ref_correct / 18) * 100
    pct_ref_wrong = (ref_wrong / 18) * 100

    answerable_accuracy = (ans_correct / 15) * 100
    ood_refusal_accuracy = (ref_correct / 3) * 100

    summary_data = {
        "setting": "improved-hybrid-rrf-rerank",
        "model": GROQ_MODEL,
        "total_questions": 18,
        "answerable_questions": 15,
        "ood_questions": 3,
        "correct_answers": ans_correct,
        "answerable_accuracy_pct": round(answerable_accuracy, 1),
        "ood_refusal_accuracy_pct": round(ood_refusal_accuracy, 1),
        "overall_correct_pct": round(pct_correct, 1),
        "wrong_pct": round(pct_wrong, 1),
        "refused_correctly_pct": round(pct_ref_correct, 1),
        "refused_wrongly_pct": round(pct_ref_wrong, 1),
        "avg_tokens_per_request": round((total_tokens_in + total_tokens_out) / 18, 1),
        "avg_total_ms": round(sum(latencies) / len(latencies), 1) if latencies else 0,
        "avg_ttft_ms": round(sum(ttfts) / len(ttfts), 1) if ttfts else 0,
    }

    summary_filename = "retrieval_improved_summary_sim.json" if use_simulator else "retrieval_improved_summary.json"
    summary_path = os.path.join(reports_dir, summary_filename)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary_data, f, indent=2)

    print("\n" + "=" * 75)
    print("FINAL EVALUATION RESULTS:")
    print(f"  Answerable Accuracy: {ans_correct}/15 ({answerable_accuracy:.1f}%)")
    print(f"  Out-of-Domain Refusal: {ref_correct}/3 ({ood_refusal_accuracy:.1f}%)")
    print(f"  Summary: {summary_counts}")
    print(f"  Saved details to: {details_path}")
    print(f"  Saved summary to: {summary_path}")
    print("=" * 75)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulator", action="store_true", help="Use calibrated stand-in simulator")
    args = parser.parse_args()
    asyncio.run(run_improved_suite(use_simulator=args.simulator))
