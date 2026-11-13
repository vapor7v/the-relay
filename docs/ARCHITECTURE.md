# The Relay — System Architecture Documentation

## 1. Executive Summary

**The Relay** is a production-grade, rate-limited research paper Q&A pipeline engineered to query dense scientific corpora under strict provider quotas and latency constraints. The pipeline queries three landmark papers:
1. *Attention Is All You Need* (Vaswani et al., arXiv 1706.03762v7)
2. *Moshi: a speech-text foundation model for real-time dialogue* (Défossez et al., arXiv 2410.00037v1)
3. *Dynamic Chunking for End-to-End Hierarchical Sequence Modeling* (arXiv 2507.07955v2)

The system targets Groq's high-speed inference cloud (`qwen/qwen3.8-27b`) and implements a dual-mode execution engine: a real provider client with HTTP header calibration, and a mathematically calibrated stand-in simulator reproducing real-world log-normal latency and concurrency degradation.

---

## 2. Four-Stage Pipeline Architecture

Every query traverses a strictly managed four-stage pipeline orchestrated by `relay/pipeline.py`:

```
User Query
    │
    ▼
[ Admission Control ] ──(Exhausted/Timeout)──► Transparent Refusal / Error
    │ (Acquired)
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Query Analysis                                      │
│ - LLM evaluates domain answerability and extracts keywords  │
│ - Out-of-domain queries trigger immediate polite refusal     │
└─────────────────────────────────────────────────────────────┘
    │ (Answerable)
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 2: Passage Retrieval                                   │
│ - BM25/TF-IDF sparse vector search over chunked paper index │
│ - Configurations: chunk size (500/1000), top_k (3/5), rerank│
└─────────────────────────────────────────────────────────────┘
    │ (Passages retrieved)
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Answer Drafting                                     │
│ - Streaming model call synthesizing grounded response       │
│ - Captures Draft TTFT (first content token generated)       │
└─────────────────────────────────────────────────────────────┘
    │ (Draft generated)
    ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 4: Mandatory Citation Verification (Correctness-First) │
│ - LLM verifies claims against retrieved passage citations   │
│ - Hard Constraint: NEVER bypassed under quota pressure      │
│ - If invalid: regeneration loop up to max retries           │
│ - If quota exhausted during verify: draft strictly withheld │
└─────────────────────────────────────────────────────────────┘
    │ (Certified)
    ▼
User-Visible Answer Delivered (User-Visible TTFT recorded)
```

### Stage Details

1. **Step 1: Query Analysis**:
   - Classifies whether the query falls within the research paper domain.
   - Extracts focused search keywords, stripping conversational noise.
   - For out-of-domain queries (e.g. general trivia), the pipeline issues an early refusal without consuming passage retrieval or drafting tokens.

2. **Step 2: Passage Retrieval**:
   - Executes sparse retrieval over pre-indexed paper chunks.
   - Generates explicit citation metadata labels: `[Paper Title, p.X]`.
   - Supports three canonical configurations:
     - `small-5-no`: 500 characters, 5 chunks, no reranking.
     - `medium-3-no`: 1000 characters, 3 chunks, no reranking.
     - `medium-5-yes`: 1000 characters, 5 chunks, with cosine reranking.

3. **Step 3: Answer Drafting**:
   - Synthesizes an academic response strictly grounded in the retrieved passages.
   - Delivered via token-by-token Server-Sent Events (SSE).
   - Captures `draft_ttft_ms` on the arrival of the first non-metadata content token.

4. **Step 4: Citation Verification**:
   - Acts as an automated fact-checker, auditing each claim against retrieved passages.
   - Enforces correct paper attribution and valid page references.
   - Under quota exhaustion or API failure, the unverified draft is **never** leaked to the user; instead, the system returns an honest, structured refusal.

---

## 3. Dual Token-Bucket Rate Limiter & Quota Engine

The rate limiter in `relay/rate_limiter.py` manages multiple orthogonal resource dimensions:

| Resource Dimension | Free / On-Demand Limit | Real Provider Behavior |
|---|---|---|
| **Requests Per Minute (RPM)** | 30 baseline / 60 burst | Token bucket refilling continuously at $RPM / 60$ tokens/s |
| **Tokens Per Minute (TPM)** | 8,000 TPM | Token bucket refilling at $TPM / 60$ tokens/s |
| **Input Tokens Per Minute (ITPM)**| 7,000 ITPM | Enforced in Groq 429 error bodies |
| **Requests Per Day (RPD)** | 1,000 active / 14,400 tier ceiling | Strict daily counter resetting at 00:00:00 UTC |
| **Tokens Per Day (TPD)** | 500,000 TPD | Daily token counter resetting at 00:00:00 UTC |

### Key Engineering Features

- **Continuous Dual-Bucket Tracking**: Separate refill rates for requests and total/input tokens.
- **Provider Header Calibration**: Live HTTP response headers dynamically update local limiter state:
  - `retry-after`: Calibrates backoff sleep.
  - `x-ratelimit-reset-tokens`: Syncs token bucket refill timer.
  - `x-ratelimit-limit-requests`: Updates active daily request ceiling.
- **Persistent Quota State**: Daily request and token usage are atomically persisted to `experiments/logs/quota_state.json`. If the application or worker restarts mid-day, the used quota is restored, preventing quota amnesia.
- **UTC Midnight Reset**: Accurately tracks `day_reset_timestamp` against UTC midnight (`00:00:00 UTC`), aligning with Groq's daily billing window.
- **Reservation Release on Cancellation**: If a queued request is cancelled or times out, all pre-allocated tokens are credited back to the bucket immediately.

---

## 4. End-to-End Deadlines & Timeout Propagation

To prevent runaway requests and resource starvation under heavy load, the system enforces a strict deadline hierarchy:

1. **Queue Admission Timeout (`QUEUE_TIMEOUT_S = 30.0s`)**: The maximum duration a request may wait in the rate limiter admission queue before being shed.
2. **External Request Timeout (`REQUEST_TIMEOUT_S = 60.0s`)**: Per-HTTP call timeout enforced via `aiohttp.ClientTimeout`.
3. **End-to-End Pipeline Deadline (`PIPELINE_TIMEOUT_S = 120.0s`)**: A shared monotonic deadline (`time.monotonic() + PIPELINE_TIMEOUT_S`) instantiated at request entry.

```
Request Arrival (t0) ───[ Monotonic Deadline: t0 + 120s ]───────────────────────► Expiry
       │                                                                            ▲
       ├──► Step 1 (Analysis)    ── remaining = min(30s, deadline - t)              │
       ├──► Step 2 (Retrieval)   ── remaining = deadline - t                        │
       ├──► Step 3 (Drafting)    ── remaining = min(60s, deadline - t)              │
       └──► Step 4 (Verify Loop) ── remaining = min(60s, deadline - t) ─────────────┘
```

If the remaining time expires at any point:
- In-flight HTTP streams are immediately aborted.
- Concurrency slots and semaphore permits are released.
- Queue counters are decremented.
- The request transitions to status `"timeout"`.

---

## 5. Latency Telemetry: Draft TTFT vs User-Visible TTFT

Because the pipeline streams drafting internally and then executes verification before returning the verified text, draft latency and delivery latency diverge:

1. **Draft TTFT (`draft_ttft_ms`)**:
   - Monotonic duration from Step 3 LLM dispatch to the receipt of the first non-empty content token SSE event.
   - Reflects raw model inference responsiveness.
   - Recorded as `first_token_ms` in `results.csv` for schema compatibility.
2. **User-Visible TTFT (`user_visible_ttft_ms`)**:
   - Monotonic duration from initial query receipt until the complete, verified answer is available for user delivery.
   - Includes Steps 1, 2, 3, and 4.
   - Logged in the companion event stream: `experiments/logs/request_events.csv`.
3. **Total Latency (`total_ms`)**:
   - Complete elapsed duration from request intake to final delivery or error termination.
   - Invariant: `first_token_ms <= total_ms` strictly enforced; impossible measurements raise errors rather than being artificially clamped.
   - Failed requests (e.g. admission rejection, immediate rate limit) legitimately record null TTFT.

---

## 6. Stand-in Simulator Architecture

The stand-in simulator (`relay/simulator.py`) mimics the Groq API server using empirical pilot calibration:

- **Log-Normal TTFT Distribution**:
  $$\text{TTFT} = \exp(\mu + \sigma \cdot Z) + \text{load\_slowdown}$$
  Calibrated from 10 Groq pilot runs ($\text{median} = 284\text{ms}$, $\sigma = 0.9731$, $15\text{ms}$ slowdown per concurrent request).
- **Gaussian Token Generation Rate**:
  Tokens generated at $\sim 520 \pm 135\text{ tok/s}$, degrading under high concurrency down to a 30% floor.
- **Deterministic Seeding**: `SimulatorState(cal, seed=42)` guarantees 100% reproducible benchmark scenarios.
- **Context-Aware Responses**: Emulates all three pipeline prompt schemas (Query Analysis JSON, Retrieval-grounded drafting, and Citation verification JSON) with realistic token lengths.

---

## 7. Verification and Test Architecture

The system includes a 14-rule integrity auditor (`relay/validate_results.py`) and a comprehensive automated unit test suite (`tests/`):

- `tests/test_rate_limiter.py`: Deterministic bucket depletion, daily quota exhaustion, persistence across restarts, post-reset recovery, header updates, and reservation rollback.
- `tests/test_verification.py`: Unsupported claims retry loop, draft withholding under quota exhaustion, regeneration limits, verification 500 service errors, and out-of-domain refusals.
- `tests/test_timeouts.py`: Queue admission timeout, slow streaming timeout, retry backoff deadline enforcement, and queue slot release on cancellation.
- `tests/test_simulator.py`: Log-normal distribution reproducibility, concurrency bounds, prompt question extraction, and protocol mocking.
- `tests/test_validator.py`: Comprehensive positive and negative auditing of all 14 data validation rules.
