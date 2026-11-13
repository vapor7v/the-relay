# The Relay — Rate-Limited Research Paper Q&A Pipeline

A production-grade, rate-limited research paper Q&A pipeline engineered to query dense scientific corpora under strict provider quotas and latency constraints.

Built for **The Relay Assignment**, targeting Groq's high-speed inference cloud (`qwen/qwen3.8-27b`) alongside a mathematically calibrated stand-in simulator reproducing real-world log-normal latency and concurrency degradation.

---

## 1. Corpus & Model Specification

### Primary Research Corpus
The pipeline indexes and queries three landmark machine learning papers:
1. **Attention Is All You Need** (Vaswani et al., arXiv 1706.03762v7) — The foundational Transformer architecture.
2. **Moshi: a speech-text foundation model for real-time dialogue** (Défossez et al., arXiv 2410.00037v1) — Full-duplex speech-text foundation model.
3. **Dynamic Chunking for End-to-End Hierarchical Sequence Modeling** (arXiv 2507.07955v2) — Learned adaptive token segmentation.

All three PDFs are stored and pre-indexed in `relay/papers/`.

### Inference Engine
- **Target Model**: `qwen/qwen3.8-27b`
- **Hosted Cloud Provider**: Groq On-Demand / Free Tier API (streaming SSE).
- **Calibrated Stand-in Simulator**: In-process HTTP SSE server calibrated to empirical Groq profiling ($\mu=\ln(284)$, $\sigma=0.9731$, bounded TPS, load-dependent degradation).

---

## 2. Key Architectural Features

- **Four-Stage Pipeline**:
  1. *Step 1: Query Analysis*: Classifies domain answerability and extracts focused search keywords.
  2. *Step 2: Passage Retrieval*: TF-IDF sparse vector retrieval over chunked paper texts with page tracking.
  3. *Step 3: Answer Drafting*: Streaming synthesis with token-by-token generation and draft TTFT tracking.
  4. *Step 4: Citation Verification*: Automated fact-checker verifying claims against retrieved primary sources. **Hard constraint: Never bypassed under quota or budget pressure.**
- **Dual Token-Bucket Admission Control**: Models RPM (30 baseline/60 burst), TPM (8,000), ITPM (7,000 ceiling), RPD (1,000 active / 14,400 tier ceiling), and TPD (500,000). Updates dynamically from provider HTTP headers (`retry-after`, `x-ratelimit-*`).
- **Persistent Quota State**: Tracks usage against 00:00:00 UTC and persists daily quota state to `experiments/logs/quota_state.json` across process restarts.
- **Hierarchical Monotonic Deadlines**: Strict timeout propagation (`QUEUE_TIMEOUT_S = 30s`, `REQUEST_TIMEOUT_S = 60s`, `PIPELINE_TIMEOUT_S = 120s`). Requests aborted on deadline immediately release queue slots and concurrency counters.
- **Accurate Latency Telemetry**: Distinguishes internal draft TTFT (`draft_ttft_ms`) from user-visible TTFT (`user_visible_ttft_ms`). Enforces `first_token_ms <= total_ms` without artificial clamping; null TTFT for refused/failed requests.

---

## 3. Quickstart & Installation

### Requirements
- Python 3.10+ (tested on Python 3.14)
- Virtual environment recommended

### Setup
```bash
# Clone or navigate to the repository
cd /path/to/Assignment

# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Configuration (`.env`)
Copy `.env.example` to `.env` and insert your Groq API key:
```bash
cp .env.example .env
```

Edit `.env`:
```ini
GROQ_API_KEY=gsk_your_actual_key_here
GROQ_MODEL=qwen/qwen3.8-27b
MODEL_PROVIDER=groq
```
> **Security Notice**: `.env` is ignored by `.gitignore` and must never be committed or included in submission archives. If `GROQ_API_KEY` is omitted, the pipeline raises a clear configuration error instead of silently masking failures.

To run against the calibrated local simulator instead of the real Groq API:
```ini
MODEL_PROVIDER=simulator
```

---

## 4. Execution & Usage

### Interactive CLI Query
Ask a grounded scientific question:
```bash
python relay/main.py ask "What is the dimensionality of d_model in the Transformer base model?"
```

Sample Output:
```
================================================================================
QUESTION: What is the dimensionality of d_model in the Transformer base model?
STATUS:   ok
LATENCY:  First Token: 320.4ms | Total: 1145.2ms
TOKENS:   In: 184 | Out: 48 | Retries: 0
VERIFIED: True
GRADE:    correct
CITATIONS: [Attention Is All You Need, p.5]
================================================================================
ANSWER:
The dimensionality of the model (d_model) in the Transformer base model is 512 [Attention Is All You Need, p.5].
```

---

## 5. Experimental Reproduction & Benchmarking

### 1. Reproducing Report Tables from Raw Data
To regenerate Tables 1, 2a, 2b, and 3 from `results.csv`:
```bash
python relay/compute_tables_from_csv.py
```
This script derives all metrics deterministically from raw request records, outputting sample sizes $(N)$ and `N/A` for zero-success scenarios.

### 2. Validating Results Integrity (14 Validation Rules)
Run the strict data auditor:
```bash
python relay/validate_results.py
```
Audits:
- Schema column integrity (exact 12 columns).
- Zero duplicate request IDs.
- Valid status, grades, and sources.
- Nonnegative tokens, retries, and durations.
- Physical coherence: `first_token_ms <= total_ms` (no artificial clamping).
- Zero credential leakage in CSV or Markdown reports.

### 3. Re-running the 18-Question Retrieval Evaluation
To execute the frozen 18-question benchmark across all 3 retrieval configurations:
```bash
python relay/run_retrieval_experiment.py
```
Outputs claim-by-claim evaluation breakdown to `experiments/reports/retrieval_evaluation_details.json`.

### 4. Running Load Benchmark Scenarios
To run load scenarios against the calibrated simulator:
```bash
# Run steady-state baseline
python relay/runner.py --scenario steady

# Run burst traffic scenario
python relay/runner.py --scenario burst

# Run sustained overload (120 req/min)
python relay/runner.py --scenario sustained_overload

# Run halved rate limit scenario
python relay/runner.py --scenario per_minute_limit_halved

# Run daily quota exhaustion scenario
python relay/runner.py --scenario daily_budget_exhausted
```

### 5. Compiling the 2-Page Technical Report PDF
Generate `report.pdf` directly from `report.md`:
```bash
python relay/generate_pdf.py
```
Dynamically verifies that the compiled document does not exceed the strict 2-page specification.

---

## 6. Automated Test Suite

Run the full pytest suite (31 unit tests):
```bash
pytest tests/ -v
```

Test coverage includes:
- `tests/test_rate_limiter.py`: Token bucket refilling, daily budget exhaustion, quota persistence across restarts, post-reset recovery, HTTP header calibration, reservation rollback.
- `tests/test_verification.py`: Unsupported claim retry loops, draft withholding under quota exhaustion, regeneration limits, verification 500 service errors, and out-of-domain refusals.
- `tests/test_timeouts.py`: Queue admission timeout, slow streaming timeout, retry backoff deadline aborts, queue slot release on cancellation.
- `tests/test_simulator.py`: Deterministic seed reproducibility, concurrency tracking, prompt parsing, context-aware responses.
- `tests/test_validator.py`: Positive and negative verification of all 14 data integrity constraints.

---

## 7. Project Structure

```
├── .env.example                          # Template for environment configuration
├── .gitignore                             # Git ignore rules (protects credentials & venv)
├── README.md                              # Project documentation and reproduction guide
├── requirements.txt                       # Pinned Python package dependencies
├── results.csv                            # Official 124-row raw experimental data
├── results_original_backup.csv            # Immutable backup of original experiment run
├── report.md                              # 2-page technical report in Markdown
├── report.pdf                             # Compiled 2-page publication-quality PDF
├── docs/
│   ├── ARCHITECTURE.md                    # Deep architectural documentation
│   ├── CHECKLIST.md                       # Comprehensive requirements and audit checklist
│   ├── conversation_history.md            # Sanitized interaction log
│   └── FINAL_AUDIT.md                     # Engineering correction pass findings & fixes
├── experiments/
│   ├── logs/
│   │   ├── quota_state.json               # Persistent daily quota state
│   │   ├── request_events.csv             # Granular companion telemetry events
│   │   └── scenario_metadata.json         # High-resolution benchmark metadata
│   └── reports/
│       └── retrieval_evaluation_details.json # 18-question claim-by-claim evaluation
├── relay/
│   ├── config.py                          # Settings, model profiles, and rate limit configs
│   ├── pipeline.py                        # 4-stage pipeline orchestrator
│   ├── rate_limiter.py                    # Multi-dimensional dual token-bucket rate limiter
│   ├── llm_client.py                      # Groq streaming HTTP client with timeout propagation
│   ├── simulator.py                       # Calibrated stand-in HTTP SSE server
│   ├── indexer.py                         # PDF extraction & TF-IDF sparse vector search
│   ├── questions.py                       # Frozen 18-question evaluation suite & ground truth
│   ├── runner.py                          # Load testing harness & scenario runner
│   ├── csv_logger.py                      # 12-column results logger and companion event logger
│   ├── compute_tables_from_csv.py         # Deterministic table derivation script
│   ├── validate_results.py                # 14-rule integrity and schema auditor
│   ├── generate_pdf.py                    # Markdown-to-PDF compiler with page count audit
│   ├── run_retrieval_experiment.py        # 18-question evaluation runner
│   └── papers/                            # Local PDFs for the 3 research papers
└── tests/
    ├── test_rate_limiter.py
    ├── test_simulator.py
    ├── test_timeouts.py
    ├── test_validator.py
    └── test_verification.py
```
