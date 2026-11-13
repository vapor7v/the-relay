# The Relay — Final Engineering Verification Checklist

This document provides a comprehensive verification audit of **The Relay** research paper Q&A pipeline against all requirements specified in **The Relay Assignment Brief** and the **Final Engineering Correction Pass (Parts 1–17)**.

---

## 1. Core Architecture & Pipeline Specification

| Component | Status | Verification & Evidence |
|---|---|---|
| **Language & Environment** | **PASSED** | Python 3.14 running in dedicated venv (`/home/apurvnishit/Assignment/venv/`). |
| **Pipeline Stages ($\ge 4$ distinct steps)** | **PASSED** | Step 1: Query Analysis (LLM); Step 2: Passage Retrieval (Tool); Step 3: Answer Drafting (Streaming LLM); Step 4: Citation Verification (LLM). Implemented in `relay/pipeline.py`. |
| **Tool Call ($\ge 1$)** | **PASSED** | Step 2 passage search (`relay/indexer.py: PaperIndex.search`) executes TF-IDF sparse vector retrieval with page tracking. |
| **Branch / Loop ($\ge 1$)** | **PASSED** | Early domain refusal branch on out-of-domain questions; citation verification loop retrying drafting on invalid citations (up to `MAX_CITATION_RETRIES = 2`). |
| **Required arXiv Papers** | **PASSED** | Verified exact paper versions in `relay/papers/`: *Attention Is All You Need* (1706.03762v7), *Moshi* (2410.00037v1), *Dynamic Chunking* (2507.07955v2). |
| **Inline Academic Citations** | **PASSED** | Factual claims require bracketed citation metadata `[Paper Title, p.X]`; verified against retrieved primary-source chunks. |
| **Hosted LLM Provider** | **PASSED** | Groq cloud platform (`qwen/qwen3.8-27b`) via on-demand tier with streaming SSE client. |
| **Calibrated Stand-in Simulator** | **PASSED** | Stand-in HTTP SSE server (`relay/simulator.py`) calibrated to empirical Groq profiling ($\text{median}=284\text{ms}$, $\sigma=0.9731$, bounded TPS, concurrency degradation). |

---

## 2. Engineering Correction Pass Audit (Parts 1–17)

| Part | Description | Status | Implementation Details & Proof |
|---|---|---|---|
| **Part 1** | **Inspection, Auditing & Timestamped Backups** | **PASSED** | Full codebase, results, report, and logs audited. Timestamped backup created in `backups/backup_20261114_023712/`. Created comprehensive issue audit in `docs/FINAL_AUDIT.md`. |
| **Part 2** | **API Key & Configuration Management** | **PASSED** | `python-dotenv` loads `.env`. API key fetched via `os.getenv("GROQ_API_KEY")` with no hardcoded fallback. `.env` added to `.gitignore`. `.env.example` created with empty values. Sanitized conversation history and validated zero credentials in results/report. |
| **Part 3** | **Rate Limiter Configuration & Provider Limits** | **PASSED** | Explicitly models RPM (30 baseline/60 burst), TPM (8,000), ITPM (7,000 ceiling), RPD (1,000 active cap / 14,400 tier ceiling), TPD (500,000). Dynamically updates from provider HTTP headers (`retry-after`, `x-ratelimit-*`). |
| **Part 4** | **Draft TTFT vs User-Visible TTFT** | **PASSED** | Separated internal `draft_ttft_ms` (arrival of first non-empty draft content token) from `user_visible_ttft_ms` (completion of verification certification). `time.monotonic()` used across all measurements; impossible measurements raise errors without artificial clamping. |
| **Part 5** | **Semantic Evaluation & Retrieval Investigation** | **PASSED** | Frozen 18-question suite with structured ground truth (`required_claims`, `optional_details`, `expected_paper`, `expected_citation`). Solved retrieval trap in simulator keyword parser. Outputted claim-by-claim evaluation artifact: `experiments/reports/retrieval_evaluation_details.json`. |
| **Part 6** | **Citation Verification (Correctness-First Policy)** | **PASSED** | Never bypassed under budget or quota pressure. If daily quota or tokens are exhausted at Step 4, unverified drafts are strictly withheld and an honest refusal is served. Tested via unit tests. |
| **Part 7** | **End-to-End Deadlines & Cancellation** | **PASSED** | Hierarchical deadlines: `QUEUE_TIMEOUT_S = 30.0s`, `REQUEST_TIMEOUT_S = 60.0s`, `PIPELINE_TIMEOUT_S = 120.0s`. Monotonic deadline propagated through all model calls and retry loops. Cancellation immediately releases queue slots and concurrency counters. |
| **Part 8** | **Daily Quota Reset Behavior** | **PASSED** | Tracks daily reset at 00:00:00 UTC. Persists daily request/token usage to `experiments/logs/quota_state.json`, preventing quota amnesia across process restarts. |
| **Part 9** | **Experimental Reproducibility & Schema** | **PASSED** | Preserved exact 12-column `results.csv` schema (124 official rows). High-resolution companion logs: `experiments/logs/request_events.csv` and `experiments/logs/scenario_metadata.json`. `compute_tables_from_csv.py` derives all 4 tables deterministically. |
| **Part 10** | **Load Test Statistics & Honest Reporting** | **PASSED** | Sample size $(N)$ reported alongside every latency percentile (e.g. `p50/p95/p99 (N=4)`). Scenarios with 0 successful responses display `N/A` for Cost/1k. Separated successful vs failed request costs. |
| **Part 11** | **Strengthen Results Validator** | **PASSED** | `relay/validate_results.py` audits 14 distinct integrity rules without clamping. Verified exit code 0 on `results.csv` and `report.md`. Automated unit tests in `tests/test_validator.py`. |
| **Part 12** | **PDF Report Generation ($\le 2$ Pages)** | **PASSED** | `relay/generate_pdf.py` dynamically parses `report.md` (no hardcoded prose). Generates `report.pdf` programmatically verified at exactly 2 pages. |
| **Part 13** | **Project Documentation & Architecture** | **PASSED** | Created `docs/ARCHITECTURE.md`, `docs/FINAL_AUDIT.md`, `requirements.txt`, updated `CHECKLIST.md` and `README.md`. |
| **Part 14** | **Automated Unit Testing** | **PASSED** | 31 unit tests across `tests/` covering rate limiting, timeouts, verification, simulator, and validator: 100% pass rate. |
| **Part 15** | **Clean Submission Packaging** | **PASSED** | Created `the_relay_submission.zip` containing all code, documentation, reports, and tests, excluding `.env`, virtualenvs, bytecode, and temp files. |

---

## 3. Test Suite Verification Summary

```
pytest tests/ -v
======================== 31 passed, 1 warning in 17.37s ========================
- tests/test_rate_limiter.py: 6/6 PASSED
- tests/test_simulator.py:    7/7 PASSED
- tests/test_timeouts.py:     4/4 PASSED
- tests/test_validator.py:    9/9 PASSED
- tests/test_verification.py: 5/5 PASSED
```

---

## 4. Key Submission Deliverables

1. `results.csv`: 124 request-level records in exact 12-column schema.
2. `report.md`: Technical report with 8 standard sections, user feedback, and Tables 1, 2a, 2b, 3.
3. `report.pdf`: Exact 2-page publication-quality PDF generated from `report.md`.
4. `conversation_history.md`: Complete, sanitized agent interaction history.
5. `CHECKLIST.md`: This verification document.
6. `README.md`: Setup, reproduction, testing, and execution instructions.
7. `docs/ARCHITECTURE.md`: Deep architectural documentation.
8. `docs/FINAL_AUDIT.md`: Pre-pass audit findings and technical resolutions.
9. `the_relay_submission.zip`: Verified clean submission archive.
