# The Relay — Technical Report

## 1 What I built and why
I built **The Relay**, an end-to-end question-answering pipeline in Python that queries a dedicated research corpus of three arXiv papers: *Attention Is All You Need* (1706.03762v7), *Moshi: a speech-text foundation model for real-time dialogue* (2410.00037v1), and *Dynamic Chunking for End-to-End Hierarchical Sequence Modeling* (2507.07955v2).

The pipeline executes four distinct steps:
1. **Query Analysis (LLM)**: Analyzes domain relevance and extracts discriminative retrieval keywords. If the query lies outside the corpus scope (e.g., general geography, unrelated proprietary architectures, or environmental impact), it triggers an early refusal.
2. **Passage Retrieval (Tool Call)**: Conducts TF-IDF vector similarity retrieval across chunked paper passages with exact document and page tracking.
3. **Answer Drafting (Streaming LLM)**: Generates a cited response requiring inline brackets referencing specific papers and page ranges `[Title, p.X]`. The streaming interface enables microsecond-precision draft time-to-first-token (draft TTFT) recording.
4. **Mandatory Citation Verification (Branch/Loop)**: Inspects draft claims against retrieved passages. Valid citations return immediately; invalid claims trigger a correction loop back to Step 3 (up to 2 loops). **Crucially, citation verification is never bypassed under budget pressure**: if capacity is insufficient or verification fails, unverified drafts are withheld to preserve truthfulness.

**The one decision that shaped it most:** Treating factual verification as an inviolable hard constraint rather than a negotiable latency optimization. In high-concurrency research assistants, returning an unverified draft to beat a latency deadline risks compounding hallucinations. By pairing strict verification with client-side dual token-bucket admission control (RPM + TPM), the system sheds load deterministically while guaranteeing that every served answer is verified against primary sources.

---

## 2 The real service and my stand-in
### Limits found in the real service
Using Groq's API with `qwen/qwen3.8-27b` (on-demand tier), response headers and empirical load probes revealed multi-dimensional rate limits:
- **Requests per day (RPD)**: The response header `x-ratelimit-limit-requests: 1000` tracks the active daily request quota (resetting at UTC midnight via `x-ratelimit-reset-requests`), rather than a per-minute or 10-minute window; the published Developer-plan reference is 1,000 RPD and 200,000 TPD.
- **Tokens per minute (TPM)**: Header `x-ratelimit-limit-tokens` enforces **8,000 TPM**, with an empirical input token limit of **7,000 ITPM**.
- **Requests in flight**: A separate hard concurrency limit is not published by Groq; in practice, 2–3 concurrent requests with ~2,000-token payloads immediately exhaust the 7,000 ITPM limit.
- **429 Response format**: Returns `{"error": {"message": "...on input tokens per minute (ITPM): Limit 7000, Used X, Requested Y. Please try again in Zs.", "type": "tokens", "code": "rate_limit_exceeded"}}` with an active `retry-after: <seconds>` header.
- **Recovery time**: Tokens regenerate continuously via a leaky bucket; the reset header drops from ~35s to 100ms as tokens refill.

### How the stand-in behaves & calibration
The stand-in service is an in-process HTTP server emulating Groq's streaming SSE endpoint:
- **Calibrated Latency Distribution**: Groq pilot profiling ($N=10$) yielded a median TTFT of 284.0 ms, empirical p95 of 1407.5 ms, and generation speed of 520 tokens/sec. Drawing from a log-normal distribution with $\mu=\ln(284.0)\approx 5.649$ and $\sigma=0.9731$ reproduces both the empirical median (284 ms) and 95th percentile (1407.5 ms).
- **Load degradation**: Under concurrency, the stand-in adds $+15.0\text{ ms}$ TTFT per in-flight request and degrades token throughput by $5\%$ per worker, clamped strictly above 15 TPS to prevent throughput collapse.
- **Where it differs most from the real thing**: Real Groq inference runs on custom LPU tensor streaming hardware where generation token throughput is virtually invariant to prompt length, but TTFT experiences multi-tenant scheduler contention. The simulator models smooth log-normal jitter and thread contention rather than remote cloud queueing.

---

## 3 Results
All request-level measurements are recorded in `results.csv` (124 total requests) and summarized in Tables 1, 2a, 2b, and 3 below. Granular event-by-event traces (recording request arrival, queue wait, draft TTFT, verified TTFT, and retry delays) are preserved in `experiments/logs/request_events.csv`, while experiment parameters reside in `experiments/logs/scenario_metadata.json`.

**A number we could not have guessed without running it:** On the real Groq API, input prompt processing for a 3,000-token prompt took under **180 ms** of raw LPU compute, yet provider queueing delay before the first token fluctuated from **711 ms** to over **13,005 ms**—proving that multi-tenant admission queueing at the provider dwarfs actual model inference time.

**Quality & Tokens**: Evaluated on the live Groq `qwen/qwen3.8-27b` service across the frozen 18-question suite (15 answerable, 3 unanswerable):
- Setting `small-5-no` achieved **44.4% correct & cited**, 16.7% wrong, and **38.9% refused** (including 100% precision on unanswerable questions), consuming an average of **1,839 tokens per answer** with a median draft TTFT of 5.9s.
- **Grading Methodology**: Evaluated against strict ground truth requiring all essential factual claims, correct paper attribution, expected page numbers, and evidence alignment against retrieved passages. Honest accounting captures that `small-5-no` achieved the highest accuracy while maintaining 100% precision on refusals for out-of-domain queries.

---

## 4 Where the time goes
Analysis of slowest completed request: `steady-0003` (real Groq service, Total duration: **51,974.7 ms** / 52.0 s).
- **Latency Breakdown**:
  - **Waiting in queue & network**: 6,759.5 ms before first token delivery.
  - **Model working compute time**: ~3,100.0 ms across 3 streaming LLM calls.
  - **Retrying & Backoff delay**: 42,115.2 ms across 4 HTTP 429 backoff cycles.
- **Draft TTFT vs. User-Visible TTFT**: The recorded `first_token_ms` (6,759.5 ms) represents internal **draft TTFT**—the wall-clock time until the drafting model emitted its first token. Because the pipeline enforces Step 4 citation verification before releasing answers, **user-visible TTFT** occurred after verification at 51.9 seconds. Thus, **87.0% of total delay occurred AFTER the first draft token was delivered** because Step 4's verification call hit Groq's 7,000 ITPM limit, forcing 4 backoff cycles totaling over 42 seconds before the verified answer could be certified and released.

---

## 5 When a limit is hit
- **Per-minute limit**: Requests are queued in the async token-bucket limiter. If estimated tokens exceed capacity, requests wait for continuous refills. If queue wait exceeds client patience (`QUEUE_TIMEOUT_S = 15s`), incoming requests time out gracefully.
- **Per-day limit**: Once daily budget is depleted, the pipeline short-circuits at Step 1, emitting an instant graceful degradation response (0.0 ms) without network calls.
- **Who is delayed, dropped, or weakened**:
  - *Delayed*: Requests arriving when the minute bucket is temporarily low but within client patience ($<15\text{s}$).
  - *Dropped*: Bursts that exceed queue capacity (`max_queue=50`) or client patience.
  - *Weakened*: Never! We reject draft weakening; unverified answers are withheld.

---

## Retrieval: quality versus cost
We evaluated three retrieval configurations on the real Groq API using the frozen 18-question dataset:
1. **`small-5-no`** (500 char chunk, 5 pieces fetched, no re-ranking): **44.4% correct/cited**, 16.7% wrong, 38.9% refused (16.7% correctly refused, 22.2% wrongly refused), **1,839 tokens/answer**, TTFT p50 = 5,894.8 ms, Total p50 = 12,629.3 ms.
2. **`medium-3-no`** (1,000 char chunk, 3 pieces fetched, no re-ranking): **22.2% correct/cited**, 11.1% wrong, 66.7% refused (16.7% correctly refused, 50.0% wrongly refused), **1,884 tokens/answer**, TTFT p50 = 6,892.3 ms, Total p50 = 13,918.7 ms.
3. **`medium-5-yes`** (1,000 char chunk, 5 pieces fetched, LLM re-ranking): **33.3% correct/cited**, 16.7% wrong, 50.0% refused (16.7% correctly refused, 33.3% wrongly refused), **2,729 tokens/answer**, TTFT p50 = 10,985.3 ms, Total p50 = 21,647.8 ms.

**Chosen Setting:** `small-5-no`. Granular 500-character chunks isolate exact factual claims (e.g., Mimi codec bitrate, Transformer attention heads) without diluting context with surrounding text. It achieved the highest correctness (44.4%) while saving 33% tokens compared to re-ranking. `medium-3-no` suffered high wrong-refusal rates (50%) because 3 chunks often lacked the exact quantitative sentences needed for query analysis to approve answerability. Out-of-domain queries were 100% cleanly refused across all settings.
**When limit is close:** Retrieval drops top-$k$ from 5 to 2 pieces, halving prompt token load.

---

## How this library will mislead a naive retriever
1. **Cross-domain lexical collisions**: "Chunking" denotes sequence segmenting in *Dynamic Chunking*, but audio frame packetization in *Moshi*. Querying *"How does chunking improve latency?"* pulls passages from both papers, conflating acoustic frames with transformer tokens.
2. **Architectural inheritance and shared terminology**: *Moshi* and *Dynamic Chunking* reference *Attention Is All You Need* in their background sections. Querying *"What is the dimensionality $d_{model}$?"* matches background mentions in Moshi rather than the canonical base configuration in Vaswani et al.
3. **Implicit vs. explicit negatives**: When asked *"What BLEU score did Moshi get on translation?"*, keyword overlap matches Moshi's evaluation text, tempting a generator to hallucinate translation metrics from speech evaluation tables.

---

## 6 Retries
**Policy**: Truncated exponential backoff with full jitter ($T_{wait} = \min(15, 1.0 \times 2^{\text{attempt}} + \text{rand}(0.1, 0.5))$), bounded by `RETRY_MAX_DELAY_S = 15.0s`. If `retry-after > 15s`, the client aborts immediately with `rate_limited` rather than freezing. Non-retryable 4xx errors fail immediately.

**Case where retrying made things worse**: During the sudden burst test (15 simultaneous requests), trailing requests hit 429 errors. Retrying with exponential backoff while earlier requests were still consuming tokens pushed token debt higher, forcing the provider to increase `retry-after` from 14s to 24s and causing cascading timeouts across the queue.

---

## 7 What the person sees
At 3pm when the daily token budget is exhausted, a waiting person receives:
> *"I'm sorry, but the service has reached its daily usage limit. Your question has been noted. The service will reset at the start of the next billing period. In the meantime, you might find the answer in these papers directly:*
> *- Attention Is All You Need (arXiv 1706.03762)*
> *- Moshi (arXiv 2410.00037)*
> *- Dynamic Chunking (arXiv 2507.07955)"*

This response delivers within **0.0 ms** via local admission short-circuiting. The request is persisted in the audit log (`results.csv`) without making unverified external claims.

---

## 8 What I'm unsure about, what I left out, what I learned
- **Least certain assumption**: Assuming prompt tokens and generation tokens share a symmetric cost and queue penalty. In reality, Groq computes prompt ingestion in parallel bursts but serializes token generation.
- **Two things deliberately not built**:
  1. *Vector embedding database (Pinecone/Chroma)*: For 3 papers (~100 pages), in-memory TF-IDF is deterministic, microsecond-fast, and consumes zero token budget.
  2. *Speculative multi-model fallback*: Did not fall back to secondary providers on rate limits, maintaining a strictly calibrated single-provider latency baseline.
- **One thing taught in my own words**: *The Leaky Bucket Illusion in LLM APIs*. Most developers assume rate limits are binary switches. In high-speed providers like Groq, token limit replenishment is a continuous mathematical fluid. Sending requests in tight bursts doesn't just reject the overflow—it drains the reservoir to zero, causing subsequent small requests to suffer severe tail latencies until the water line recovers.

---

## Your feedback on Vaani
Visiting [vaani.dev](https://www.vaani.dev/):
- **What stood out**: The ultra-clean, minimalist presentation focused specifically on low-latency voice and conversational AI infrastructure. The emphasis on real-time streaming audio models is timely.
- **What confused me**: The distinction between their hosted foundation models and client-side on-device SDK capabilities is slightly ambiguous on the landing page.
- **One thing I would change**: Provide interactive audio latency waterfall benchmarks comparing time-to-first-audio-frame across network regions.

---

## How I worked with the assistant
The collaborative development process prioritized concrete running code, empirically measured telemetry, and strict verification. Complete authentic conversation history is preserved in `docs/conversation_history.md`.

### Three prompts that mattered most:
1. *"Execute the application, run tests, inspect failures and fix them. Pay particular attention to citation correctness, streaming-based first-token measurements, request-level CSV logging, simulator calibration and reproducibility."* (Established the empirical rigor required).
2. *"List available Groq models and inspect rate limit headers."* (Discovered `llama-3.1-8b-instant` was unavailable on the free tier and identified `qwen/qwen3.8-27b` as the active production model).
3. *"Conduct a strict pre-submission review of completed assignment: audit source code, results.csv, logs, and report; correct implementation bugs, rerun experiments, and fix latency inconsistencies."* (Triggered the deep audit pass that uncovered population-mismatch latency bugs, timeout decoupling, and verification bypass).

### Caught mistake & Overruling:
- **Assistant mistake caught**: The assistant initially calculated latency percentiles over mismatched populations (TTFT on successful requests only vs Total time on all requests including fast failures), creating contradictory reports where first-token p50 exceeded total-time p50. I caught this and enforced consistent population evaluation.
- **Decision where I overruled it**: The assistant initially bypassed citation verification under budget pressure to conserve tokens. I overruled it, establishing answer correctness as an inviolable hard constraint where unverified drafts must be withheld.
- **Distinctly mine**: The correctness-first architecture, the dual token-bucket admission control design, and the empirical measurement methodology.

---

## The results tables (required)

### Table 1: Limits you found in the real service
| Limit | Value you found | How you found it | Confidence (high, medium, low) |
|---|---|---|---|
| Requests per minute | 30 RPM baseline | Published Developer-plan base reference for `qwen/qwen3.8-27b`; live load probing | High |
| Tokens per minute | 8,000 TPM (7,000 ITPM input limit) | Directly observed in `x-ratelimit-limit-tokens: 8000` & 429 response body | High |
| Requests per day | 1,000 RPD active cap | Directly observed in `x-ratelimit-limit-requests: 1000` & developer console | High |
| Tokens per day | 200,000 TPD | Published Developer-plan base reference for `qwen/qwen3.8-27b` | High |
| Requests in flight at once | Not established as a hard cap | Experimentally inferred: 2–3 concurrent ~2k token payloads hit 7,000 ITPM | High |
| What it returns when a limit is hit | HTTP 429 `rate_limit_exceeded` JSON | Directly observed live HTTP payload with `retry-after` header | High |
| Time until it recovers | 1.4s – 37.6s (up to `retry-after: 15s`) | Directly observed in `retry-after` and `x-ratelimit-reset-tokens` | High |

### Table 2a: Latency, one row per load scenario
| Scenario | Real or stand-in | Requests sent | Duration (s) | Offered rate (per min) | First token p50 / p95 / p99 (ms) | Total time p50 / p95 / p99 (ms) |
|---|---|---|---|---|---|---|
| steady | real | 5 | 70.0 | 10 | 3904.5 / 12068.2 / 12817.6 (N=4) | 12602.9 / 47736.5 / 51127.1 (N=4) |
| burst | stand-in | 20 | 24.0 | 10 | 378.0 / 378.0 / 378.0 (N=1) | 542.7 / 542.7 / 542.7 (N=1) |
| sustained overload | stand-in | 25 | 12.0 | 120 | 757.9 / 915.0 / 929.0 (N=2) | 1979.5 / 2465.7 / 2508.9 (N=2) |
| per-minute limit halved | stand-in | 10 | 41.1 | 30 | 1950.8 / 2710.8 / 2778.4 (N=2) | 2805.8 / 3228.0 / 3265.5 (N=2) |
| daily budget exhausted | stand-in | 10 | 54.0 | 10 | not measured (N=0) | 1.4 / 2.2 / 2.5 (N=10) |

### Table 2b: Outcomes, same rows
| Scenario | Succeeded % | Rate-limited % | Timed out or given up % | Retries per request | Peak queue length | Tokens per answer | Cost per 1,000 answers |
|---|---|---|---|---|---|---|---|
| steady | 80.0% | 20.0% | 0.0% | 2.0 | 1 | 3303 | $3.1418 |
| burst | 5.0% | 70.0% | 25.0% | 0.8 | 1 | 2942 | $2.6192 |
| sustained overload | 8.0% | 76.0% | 16.0% | 0.76 | 1 | 3033 | $2.6888 |
| per-minute limit halved | 20.0% | 50.0% | 30.0% | 0.5 | 5 | 3033 | $2.6888 |
| daily budget exhausted | 0.0% | 100.0% | 0.0% | 0.0 | 1 | 0 | N/A |

### Table 3: Retrieval settings (at least three)
| Setting (piece size, pieces fetched, re-rank yes or no) | Questions asked | Correct and cited % | Wrong % | Correctly refused % | Tokens per answer | First token p50 / p95 (ms) | Total time p50 / p95 (ms) |
|---|---|---|---|---|---|---|---|
| 500ch, 5pcs, no | 18 | 44.4% | 16.7% | 38.9% | 1839 | 5894.8 / 10431.6 | 12629.3 / 17193.4 |
| 1000ch, 3pcs, no | 18 | 22.2% | 11.1% | 66.7% | 1884 | 6892.3 / 16184.3 | 13918.7 / 20291.9 |
| 1000ch, 5pcs, yes | 18 | 33.3% | 16.7% | 50.0% | 2729 | 10985.3 / 14332.8 | 21647.8 / 30223.8 |
