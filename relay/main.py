"""Main entry point for The Relay pipeline.

Usage:
    python main.py index          Build paper index
    python main.py ask "question" Ask a single question (real Groq or --sim)
    python main.py profile        Profile Groq latency/limits
    python main.py simulate       Start the simulator server
    python main.py test           Run all test questions (--sim optional)
"""
import asyncio
import os
import sys
import time
import json
from typing import Optional

# Ensure relay package is importable
sys.path.insert(0, os.path.dirname(__file__))

from config import (
    get_groq_api_key, GROQ_MODEL, MODEL_PROFILES,
    DEFAULT_RETRIEVAL, RETRIEVAL_SETTINGS, RESULTS_CSV,
    SIMULATOR_DEFAULT_CONFIG,
)
from indexer import PaperIndex
from llm_client import LLMClient
from rate_limiter import TokenBucketRateLimiter
from csv_logger import CSVLogger
from pipeline import Pipeline, PipelineResult
from questions import QUESTIONS

INDEX_PATH = os.path.join(os.path.dirname(__file__), "paper_index.pkl")


def cmd_index():
    """Build the default paper index."""
    print("Building paper index from corpus PDFs...")
    idx = PaperIndex()
    idx.build(chunk_size=DEFAULT_RETRIEVAL.chunk_size, overlap=DEFAULT_RETRIEVAL.chunk_overlap)
    idx.save(INDEX_PATH)
    print(f"Index successfully saved to {INDEX_PATH}")

    # Sanity checks
    print("\n--- Retrieval Sanity Checks ---")
    for query in ["multi-head attention mechanism", "speech dialogue model", "dynamic chunking"]:
        results = idx.search(query, top_k=2)
        print(f"\nQuery: '{query}'")
        for r in results:
            print(f"  {r.citation_label()}: {r.text[:80]}...")


async def cmd_ask(question: str, use_simulator: bool = False):
    """Ask a single question and display verified answer with telemetry."""
    idx = PaperIndex()
    if not os.path.exists(INDEX_PATH):
        print(f"Index not found at {INDEX_PATH}. Building index first...")
        cmd_index()
    idx.load(INDEX_PATH)

    if use_simulator:
        from simulator import run_simulator
        run_simulator()

    source = "stand-in" if use_simulator else "real"
    api_key = None if not use_simulator else "sim-key"

    try:
        llm = LLMClient(use_simulator=use_simulator, api_key=api_key)
    except ValueError as e:
        print(f"\n[Configuration Error] {e}")
        sys.exit(1)

    rl_config = SIMULATOR_DEFAULT_CONFIG if use_simulator else MODEL_PROFILES.get(GROQ_MODEL, MODEL_PROFILES["qwen/qwen3.8-27b"])
    rl = TokenBucketRateLimiter(rl_config)
    logger = CSVLogger()
    pipe = Pipeline(idx, llm, rl, logger)

    print(f"Submitting query ({source} provider, model: {GROQ_MODEL}): {question}\n")
    try:
        result = await pipe.run(question, scenario="manual", source=source)
    except Exception as e:
        print(f"[Execution Error] Pipeline failed: {e}")
        await llm.close()
        sys.exit(1)

    # Safe formatting of nullable TTFT measurements
    ttft_disp = f"{result.first_token_ms:.1f} ms" if result.first_token_ms is not None else "null (no tokens generated)"
    uv_ttft_disp = f"{result.user_visible_ttft_ms:.1f} ms" if result.user_visible_ttft_ms is not None else "null"

    print("=" * 70)
    print("PIPELINE EXECUTION TELEMETRY")
    print("=" * 70)
    print(f"Status:             {result.status}")
    print(f"Answer Grade:       {result.answer_grade}")
    print(f"Draft TTFT:         {ttft_disp}")
    print(f"User-Visible TTFT:  {uv_ttft_disp}")
    print(f"Total Duration:     {result.total_ms:.1f} ms")
    print(f"Tokens:             {result.tokens_in} in, {result.tokens_out} out")
    print(f"Retries / Loops:    {result.retries}")
    print(f"Verification:       {'PASSED' if result.verification_passed else 'WITHHELD / FAILED'}")
    print("\nANSWER:")
    print("-" * 70)
    print(result.answer)
    print("-" * 70)

    await llm.close()
    return result


async def cmd_profile(num_requests: int = 5):
    """Empirically profile Groq latency and rate limit headers."""
    print("Profiling Groq API on-demand tier...")
    try:
        api_key = get_groq_api_key()
        print(f"Model: {GROQ_MODEL} (Credentials configured securely in .env)")
    except ValueError as e:
        print(f"\n[Configuration Error] {e}")
        sys.exit(1)

    llm = LLMClient(use_simulator=False, api_key=api_key)
    results = []

    test_messages = [
        {"role": "user", "content": "Respond with the single word 'ready'."},
    ]

    for i in range(num_requests):
        print(f"\nProbe {i+1}/{num_requests}...")
        resp = await llm.chat_stream(test_messages, temperature=0, max_tokens=10)
        ttft_str = f"{resp.first_token_time_ms:.1f} ms" if resp.first_token_time_ms is not None else "null"
        print(f"  Status: {resp.status} | TTFT: {ttft_str} | Total: {resp.total_time_ms:.1f} ms")
        if resp.headers:
            print("  Response Headers:")
            for k in ["x-ratelimit-limit-requests", "x-ratelimit-limit-tokens", "x-ratelimit-remaining-tokens", "retry-after"]:
                if k in resp.headers:
                    print(f"    {k}: {resp.headers[k]}")

        results.append({
            "ttft_ms": resp.first_token_time_ms,
            "total_ms": resp.total_time_ms,
            "tokens_in": resp.tokens_in,
            "tokens_out": resp.tokens_out,
            "status": resp.status,
            "retries": resp.retries,
        })
        await asyncio.sleep(2.0)

    await llm.close()
    return results


async def cmd_test(use_simulator: bool = False, retrieval_setting=None):
    """Run all 18 test questions and grade answers rigorously."""
    idx = PaperIndex()
    if not os.path.exists(INDEX_PATH):
        cmd_index()
    idx.load(INDEX_PATH)

    if use_simulator:
        from simulator import run_simulator
        run_simulator(seed=42)

    source = "stand-in" if use_simulator else "real"
    api_key = None if not use_simulator else "sim-key"

    llm = LLMClient(use_simulator=use_simulator, api_key=api_key)
    rl_config = SIMULATOR_DEFAULT_CONFIG if use_simulator else MODEL_PROFILES.get(GROQ_MODEL, MODEL_PROFILES["qwen/qwen3.8-27b"])
    rl = TokenBucketRateLimiter(rl_config)
    logger = CSVLogger()

    setting = retrieval_setting or DEFAULT_RETRIEVAL
    pipe = Pipeline(idx, llm, rl, logger, retrieval_setting=setting)

    print(f"Evaluating {len(QUESTIONS)} test questions ({source}, setting={setting.name})...\n")

    results = []
    for q in QUESTIONS:
        result = await pipe.run(
            q["question"],
            scenario="test_suite",
            source=source,
            request_id=f"test-{q['id']}",
        )
        results.append((q, result))

        status_icon = "✓" if result.answer_grade == q["expected_grade"] else "✗"
        ft_str = f"{result.first_token_ms:.0f}ms" if result.first_token_ms is not None else "null"
        print(f"  {status_icon} [{q['id']}] Grade: {result.answer_grade:<17} "
              f"(Expected: {q['expected_grade']:<17}) "
              f"[TTFT: {ft_str}, Total: {result.total_ms:.0f}ms]")

        if not use_simulator:
            await asyncio.sleep(2.5)

    await llm.close()

    # Summary
    correct = sum(1 for q, r in results if r.answer_grade == q["expected_grade"])
    print(f"\n{'='*50}")
    print(f"Accuracy: {correct}/{len(results)} ({100*correct/len(results):.1f}%)")
    print(f"{'='*50}")

    return results


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "index":
        cmd_index()
    elif cmd == "ask":
        if len(sys.argv) < 3:
            print("Usage: python main.py ask 'your question' [--sim]")
            sys.exit(1)
        question = sys.argv[2]
        use_sim = "--sim" in sys.argv
        asyncio.run(cmd_ask(question, use_simulator=use_sim))
    elif cmd == "profile":
        n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 5
        asyncio.run(cmd_profile(n))
    elif cmd == "simulate":
        from simulator import run_simulator
        print("Starting calibrated stand-in simulator on port 8787...")
        server = run_simulator()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nShutting down simulator.")
    elif cmd == "test":
        use_sim = "--sim" in sys.argv or "--real" not in sys.argv
        asyncio.run(cmd_test(use_simulator=use_sim))
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
