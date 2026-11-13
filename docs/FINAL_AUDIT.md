# The Relay — Final Engineering Audit & Correction Plan

**Date:** 2026-11-14  
**Project:** The Relay — Research Paper Q&A Pipeline  
**Role:** Senior AI Infrastructure Engineer, Python Backend Engineer, and QA Engineer  
**Specification:** `The_Relay_Assignment_Brief.pdf` & Pre-Submission Infrastructure Audit  

---

## Executive Summary

A comprehensive pre-correction audit was conducted across the codebase, experiment manifests, results datasets, technical reports, and transcripts. The architecture is sound: the 4-step pipeline (Query Analysis → Passage Retrieval → Answer Drafting → Citation Check) cleanly implements client-side admission control, streaming-based TTFT measurement, and mandatory citation verification.

However, eleven genuine engineering defects and architectural discrepancies were identified during deep inspection. This audit document details each issue, the exact source files involved, the proposed corrections, and the precise verification methods.

A timestamped backup of the entire working repository was created prior to modifications at:
`backups/backup_20261114_023712/`

---

## Detailed Audit Findings & Action Plan

### Issue 1: Hardcoded API Credentials & Inadequate Environment Configuration
* **Source Files:** `relay/config.py` (line 9), `relay/main.py` (line 81), `conversation_history.md`.
* **Root Cause:** A live Groq API key (`gsk_...`) was hardcoded as a fallback in `relay/config.py`. Furthermore, `main.py` printed key fragments in application logs (`GROQ_API_KEY[:8]...`), and conversation logs recorded raw credentials. No `.env` or `.env.example` existed.
* **Impact:** Critical security vulnerability and violation of the assignment brief.
* **Proposed Correction:**
  1. Add `python-dotenv` dependency and load `.env` in `config.py` using `dotenv.load_dotenv()` and `os.getenv("GROQ_API_KEY")`.
  2. Eliminate all hardcoded keys and fallbacks.
  3. Display a clear configuration error if `GROQ_API_KEY` is missing instead of falling back or silently switching to mocks.
  4. Create `.env.example` with empty credential placeholders.
  5. Add `.env` to `.gitignore`.
  6. Sanitize all credentials from logs, `results.csv`, `report.md`, PDFs, and `conversation_history.md`.
* **Verification Method:** Grep for `gsk_` across the entire workspace; test application behavior when `GROQ_API_KEY` is unset.

---

### Issue 2: Rate Limiter Configuration Mismatch & Rigor
* **Source Files:** `relay/config.py`, `relay/rate_limiter.py`, `report.md` (Table 1).
* **Root Cause:** `RateLimiterConfig` defaulted to `rpm=30, tpm=15000, rpd=14400, tpd=500000`, which contradicted the documented Groq `qwen/qwen3.8-27b` observed limits (RPM=60, TPM=8000, ITPM=7000). Furthermore, the limiter lacked model-specific and provider-specific configurations (real vs simulator), and did not track reset timestamps from provider headers (`x-ratelimit-reset-requests`, `x-ratelimit-reset-tokens`).
* **Impact:** Inaccurate admission control simulations, discrepancy between code defaults and Technical Report Table 1.
* **Proposed Correction:**
  1. Refactor `RateLimiterConfig` to support model-specific configurations with separate `rpm`, `tpm`, `itpm`, `otpm`, `rpd`, `tpd`, and `max_queue`.
  2. Distinguish published limits, account-configured limits, and directly observed limits.
  3. Correctly track reset timestamps and `retry-after` delays.
  4. Implement deterministic unit tests verifying token depletion and replenishment.
* **Verification Method:** Deterministic unit tests with simulated time and token consumption.

---

### Issue 3: Latency Metric Conflation (Draft TTFT vs User-Visible TTFT) and Timestamp Clamping
* **Source Files:** `relay/pipeline.py` (lines 246–248, 350–353), `relay/llm_client.py` (lines 192–194).
* **Root Cause:**
  1. In `pipeline.py`, `first_token_ms` measured internal draft generation time. Because the pipeline performs Step 4 (Citation Verification) before releasing an answer, internal draft arrival is not user-visible.
  2. When `first_token_ms > total_ms`, code clamped `first_token_ms = total_ms`, artificially masking timing anomalies rather than diagnosing them.
* **Impact:** Misleading latency reporting and potential silent corruption of timing metrics.
* **Proposed Correction:**
  1. Implement separate metrics: `draft_ttft_ms` (time to first internal model token) and `user_visible_ttft_ms` (time when verified content is released).
  2. Enforce monotonic clock timing across all stages.
  3. If `draft_ttft_ms > total_ms` or `user_visible_ttft_ms > total_ms`, raise a strict validation error.
  4. Record `null` TTFT for requests that never produce tokens.
  5. Enforce consistent request populations for all percentile calculations.
* **Verification Method:** Unit tests verifying TTFT metrics and validation rejection of impossible timestamps.

---

### Issue 4: Permissive Answer Evaluation & Simulator Matching Flaw
* **Source Files:** `relay/pipeline.py` (`_grade_answer`), `relay/simulator.py` (`generate_response_text`), `relay/questions.py`.
* **Root Cause:**
  1. `_grade_answer` used `any(k in ans_lower for k in required_kw)`. A single keyword match gave a passing grade even if essential facts were omitted.
  2. In `simulator.py`, `generate_response_text` searched for keywords (e.g., `"simultaneous"`) against the entire prompt, including retrieved passages. Consequently, for questions q08–q13 and q17–q18, the simulator returned the `full-duplex` answer instead of question-specific responses, causing 8 questions to be marked wrong.
* **Impact:** Compromised retrieval evaluation accuracy and evaluation reproducibility.
* **Proposed Correction:**
  1. Define explicit factual criteria in `questions.py`: required claims, optional details, expected paper, expected citation/section, expected outcome (answer vs refusal), explicit failure conditions.
  2. Require all essential claims and valid citation grounding for a passing grade.
  3. Fix `simulator.py` to match keywords strictly on the extracted question, not the passage context.
  4. Generate detailed evaluation report: `experiments/reports/retrieval_evaluation_details.json`.
* **Verification Method:** Unit tests for claim verification; rerun retrieval evaluation suite.

---

### Issue 5: Citation Verification Grounding & Failure Mode Handling
* **Source Files:** `relay/pipeline.py` (Step 4), `relay/llm_client.py`.
* **Root Cause:** Citation verification was structured as a basic prompt check but lacked granular claim-to-passage matching and comprehensive test coverage for edge cases (unsupported claims, incorrect paper citations, missing page numbers, verification service 5xx failures, budget exhaustion).
* **Impact:** Risk of hallucinated claims passing if the LLM hallucinated verification approval.
* **Proposed Correction:**
  1. Maintain the inviolable correctness-first policy: verification is never bypassed to save tokens or budget.
  2. Check factual claim support against retrieved passages.
  3. On verification failure or budget exhaustion, withhold unverified drafts and return an explicit refusal.
  4. Add unit tests for all verification failure modes.
* **Verification Method:** Unit tests for unsupported claims, incorrect citations, wrong paper, and service failures.

---

### Issue 6: Real End-to-End Deadline & Timeout Propagation
* **Source Files:** `relay/pipeline.py`, `relay/llm_client.py`, `relay/rate_limiter.py`.
* **Root Cause:** Timeouts were enforced piecemeal per stage (`QUEUE_TIMEOUT_S`, `API_TIMEOUT_S`), but `llm_client.py` retry loops did not respect a shared end-to-end deadline. Retries could continue executing after `PIPELINE_TIMEOUT_S` expired.
* **Impact:** Request latency could stretch well beyond the configured deadline under heavy retry storms.
* **Proposed Correction:**
  1. Implement 3 distinct limits: Queue waiting timeout (`QUEUE_TIMEOUT_S`), External API timeout (`API_TIMEOUT_S`), and Pipeline timeout (`PIPELINE_TIMEOUT_S`).
  2. Pass a shared deadline (`deadline = t_start + PIPELINE_TIMEOUT_S`) to every model call and retry backoff.
  3. Use `asyncio.timeout()` / deadline checks to abort execution immediately once the deadline is reached.
  4. Ensure cancellation releases all queue slots, concurrency permits, and rate-limiter reservations.
* **Verification Method:** Unit tests for timeouts before admission, during model streaming, during backoff, and during verification.

---

### Issue 7: Daily Quota Reset Logic & Persistence
* **Source Files:** `relay/rate_limiter.py` (line 63), `relay/simulator.py`.
* **Root Cause:** Local quota reset used `now - self._day_start >= 86400` (24h from process start) rather than UTC midnight or provider reset timestamps. In addition, restarting the process wiped out daily counters, silently resetting exhausted quotas.
* **Impact:** Experiments requiring exhausted quotas could be invalidated by process restarts.
* **Proposed Correction:**
  1. Synchronize daily reset with provider reset timestamp headers (`x-ratelimit-reset-requests`) and UTC midnight.
  2. Support configurable reset policies in the simulator.
  3. Support persistent daily quota state to maintain exhausted quota status across process restarts.
* **Verification Method:** Tests for daily budget exhaustion, partial consumption, post-reset recovery, and process restarts.

---

### Issue 8: Telemetry Architecture & Reproducibility
* **Source Files:** `relay/compute_tables_from_csv.py`, `relay/runner.py`, `relay/csv_logger.py`.
* **Root Cause:**
  1. `compute_tables_from_csv.py` relied on `scenarios_summary.json` for queue lengths and duration with a hardcoded fallback (`peak_queue = 1`).
  2. Scenarios with 0 successful answers reported `$0.0000` cost instead of `N/A`.
  3. Lack of fine-grained event-level telemetry to trace every queue event and stage transition.
* **Impact:** Incomplete audit trail and potential skepticism regarding reported metrics.
* **Proposed Correction:**
  1. Preserve the exact 12-column `results.csv` schema required by the brief:
     `request_id,scenario,source,start_time,first_token_ms,total_ms,status,retries,tokens_in,tokens_out,retrieval_setting,answer_grade`
  2. Create companion event log: `experiments/logs/request_events.csv` (tracking arrival, queue entry/exit, stage start/end, draft tokens, verification, cancellation, queue length, concurrency).
  3. Create scenario metadata log: `experiments/logs/scenario_metadata.json`.
  4. Update `compute_tables_from_csv.py` to use telemetry, report `N/A` for cost/1k when 0 answers succeed, and separate costs of successful vs failed attempts.
* **Verification Method:** Verify that every metric in Tables 1, 2a, 2b, and 3 is derived deterministically from raw logs.

---

### Issue 9: Result Validator Completeness
* **Source Files:** `relay/validate_results.py`.
* **Root Cause:** `validate_results.py` only checked basic ranges for status, grade, and duration. It lacked validation for duplicate request IDs, categorical domain enforcement, token count nonnegativity, manifest row counts, and credential leakage.
* **Impact:** Uncaught data corruption in experimental results.
* **Proposed Correction:**
  1. Expand `validate_results.py` to verify all 14 points mandated by the brief.
  2. Add unit tests for the validator against positive and negative test fixtures.
* **Verification Method:** Run automated validator tests.

---

### Issue 10: Runtime Formatting & PDF Hardcoding Issues
* **Source Files:** `relay/main.py`, `relay/generate_pdf.py`.
* **Root Cause:**
  1. In `main.py` (lines 68, 196), `result.first_token_ms:.1f` caused unhandled `TypeError` when `first_token_ms` was `None` (for refusals/errors).
  2. In `generate_pdf.py`, report paragraphs and table cells were hardcoded duplicate strings rather than dynamically generated from `report.md` or shared structured data.
* **Impact:** Crash on manual refusals and risk of divergence between Markdown report and PDF report.
* **Proposed Correction:**
  1. Fix formatting in `main.py` to safely handle `None` TTFT values.
  2. Refactor `generate_pdf.py` to read directly from `report.md` / structured data, ensuring 100% fidelity between PDF and Markdown.
  3. Enforce exactly 2 pages for `report.pdf`.
* **Verification Method:** Ask unanswerable question via `main.py`; verify PDF page count equals 2 using PyPDF2.

---

### Issue 11: Dependency Management & Submission Packaging
* **Source Files:** Repository root.
* **Root Cause:** Missing `requirements.txt`, missing `docs/ARCHITECTURE.md`, missing standalone `tests/` directory, missing `.env.example`.
* **Impact:** Non-reproducible environment for third-party evaluators.
* **Proposed Correction:**
  1. Generate clean `requirements.txt` pinning required packages (`httpx`, `aiohttp`, `python-dotenv`, `numpy`, `scikit-learn`, `PyPDF2`, `reportlab`, `pytest`).
  2. Author comprehensive `README.md` with fresh checkout setup and execution commands.
  3. Author `docs/ARCHITECTURE.md`.
  4. Create `tests/` test suite.
  5. Package clean final submission zip excluding `.env`, virtualenvs, and bytecode.
* **Verification Method:** Automated test execution and clean archive validation.

---

## Pre-Change Verification Checklist

- [x] Complete project inspected
- [x] Original brief requirements cross-referenced
- [x] Python source files reviewed
- [x] Experimental logs and CSV backups examined
- [x] Report and PDF reviewed
- [x] 18-question evaluation dataset examined
- [x] Timestamped backup created at `backups/backup_20261114_023712/`
- [x] Audit findings documented in `docs/FINAL_AUDIT.md`
