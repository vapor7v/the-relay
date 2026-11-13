"""Central configuration for The Relay pipeline.

Strictly manages:
- Local environment variables via python-dotenv without hardcoded fallback keys
- Model-specific rate limiter configurations distinguishing published, observed, and simulated limits
- Explicit stage and end-to-end timeout definitions
- Documented model pricing and research paper corpus metadata
"""
import os
from dataclasses import dataclass, field
from typing import Optional, Dict
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load environment variables from .env
# ---------------------------------------------------------------------------
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENV_PATH = os.path.join(BASE_DIR, ".env")
if os.path.exists(ENV_PATH):
    load_dotenv(ENV_PATH)
else:
    load_dotenv()

# ---------------------------------------------------------------------------
# API Credentials & Model Configuration
# ---------------------------------------------------------------------------
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.8-27b")
MODEL_PROVIDER = os.getenv("MODEL_PROVIDER", "groq")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")


def get_groq_api_key(allow_missing: bool = False) -> str:
    """Read Groq API key from environment.
    
    Raises ValueError with a clear configuration error if missing,
    preventing silent fallback to mock responses when real provider is requested.
    """
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key and not allow_missing:
        raise ValueError(
            "Configuration Error: GROQ_API_KEY is missing or empty. "
            "Please configure your API key in a local .env file (see .env.example) "
            "or set the GROQ_API_KEY environment variable. Hardcoded fallbacks are prohibited."
        )
    return key


# ---------------------------------------------------------------------------
# Rate Limiter Configuration (Model-Specific & Account-Specific)
#
# Distinguishes:
# 1. Published limits (official documentation at console.groq.com/docs/rate-limits)
# 2. Directly observed limits (live response headers and 429 error payloads)
# 3. Simulated values (used for load scenarios on stand-in simulator)
# ---------------------------------------------------------------------------
@dataclass
class RateLimiterConfig:
    """Explicitly configurable multi-dimensional rate limits."""
    model_id: str = "qwen/qwen3.8-27b"
    rpm: int = 60                   # Requests per minute (proactive client rate)
    tpm: int = 8_000                # Total tokens per minute limit
    itpm: Optional[int] = 7_000     # Input tokens per minute limit (observed in 429 bodies)
    otpm: Optional[int] = None      # Output tokens per minute (if separately enforced)
    rpd: int = 1_000                # Requests per day (active observed cap; tier ceiling 14,400)
    tpd: int = 500_000              # Tokens per day
    max_queue: int = 50             # Max queue depth before immediate load shedding
    reset_policy: str = "utc_midnight" # "utc_midnight", "sliding_window", or "provider_header"
    # Audit documentation fields
    published_rpm: int = 30
    published_tpm: int = 8_000
    published_rpd: int = 14_400
    published_tpd: int = 500_000
    source_type: str = "observed"   # "observed", "published", "simulated"


# Model-specific profiles for Groq On-Demand / Free Tier
MODEL_PROFILES: Dict[str, RateLimiterConfig] = {
    "qwen/qwen3.8-27b": RateLimiterConfig(
        model_id="qwen/qwen3.8-27b",
        rpm=60,
        tpm=8_000,
        itpm=7_000,
        rpd=1_000,
        tpd=500_000,
        published_rpm=30,
        published_tpm=8_000,
        published_rpd=14_400,
        published_tpd=500_000,
        source_type="observed",
    ),
    "llama-3.1-8b-instant": RateLimiterConfig(
        model_id="llama-3.1-8b-instant",
        rpm=30,
        tpm=6_000,
        itpm=6_000,
        rpd=14_400,
        tpd=500_000,
        published_rpm=30,
        published_tpm=6_000,
        published_rpd=14_400,
        published_tpd=500_000,
        source_type="published",
    ),
}

# Stand-in simulator profiles
SIMULATOR_DEFAULT_CONFIG = RateLimiterConfig(
    model_id="stand-in-calibrated",
    rpm=60,
    tpm=7_000,
    itpm=7_000,
    rpd=14_400,
    tpd=500_000,
    max_queue=50,
    source_type="simulated",
)

SIMULATOR_HALVED_CONFIG = RateLimiterConfig(
    model_id="stand-in-halved",
    rpm=15,
    tpm=3_500,
    itpm=3_500,
    rpd=14_400,
    tpd=500_000,
    max_queue=50,
    source_type="simulated",
)

# ---------------------------------------------------------------------------
# Published Pricing (Hypothetical paid-tier operating cost)
# Model: qwen/qwen3.8-27b on Groq on-demand tier
# Published prices per 1,000,000 tokens:
# - Input (prompt): $0.80 / 1M tokens ($0.00000080 per token)
# - Output (completion): $4.00 / 1M tokens ($0.00000400 per token)
# (Actual usage on Free Tier is $0.00; operating cost computed for analysis)
# ---------------------------------------------------------------------------
PRICE_INPUT_PER_M = 0.80
PRICE_OUTPUT_PER_M = 4.00

# ---------------------------------------------------------------------------
# Distinct Timeouts & Retry Budgets
# 1. QUEUE_TIMEOUT_S: Max wait time in client admission queue before shedding
# 2. API_TIMEOUT_S: Max HTTP timeout per single external model API call
# 3. PIPELINE_TIMEOUT_S: End-to-end wall-clock deadline for the complete 4-step pipeline
# 4. Retry budgets: Bound backoff delays and loops
# ---------------------------------------------------------------------------
QUEUE_TIMEOUT_S = 15.0        # Client patience limit in admission queue
USER_PATIENCE_S = QUEUE_TIMEOUT_S
API_TIMEOUT_S = 30.0          # HTTP network/socket timeout
PIPELINE_TIMEOUT_S = 60.0     # End-to-end request timeout deadline

MAX_LLM_RETRIES = 3           # Max HTTP retries per model call on 429/5xx
RETRY_BASE_DELAY_S = 1.0      # Exponential backoff base
RETRY_MAX_DELAY_S = 15.0      # Cap on single retry wait
MAX_CITATION_RETRIES = 2      # Max correction loops for invalid citations

# ---------------------------------------------------------------------------
# Simulator Settings
# ---------------------------------------------------------------------------
SIMULATOR_PORT = 8787
SIMULATOR_URL = f"http://127.0.0.1:{SIMULATOR_PORT}/v1"

# ---------------------------------------------------------------------------
# Papers Corpus Metadata
# ---------------------------------------------------------------------------
PAPERS_DIR = os.path.join(os.path.dirname(__file__), "papers")
PAPERS = {
    "attention": {
        "file": "attention.pdf",
        "title": "Attention Is All You Need",
        "arxiv": "1706.03762v7",
    },
    "moshi": {
        "file": "moshi.pdf",
        "title": "Moshi: a speech-text foundation model for real-time dialogue",
        "arxiv": "2410.00037v1",
    },
    "dynamic_chunking": {
        "file": "dynamic_chunking.pdf",
        "title": "Dynamic Chunking for End-to-End Hierarchical Sequence Modeling",
        "arxiv": "2507.07955v2",
    },
}

# ---------------------------------------------------------------------------
# Retrieval Settings
# ---------------------------------------------------------------------------
@dataclass
class RetrievalSetting:
    name: str
    chunk_size: int        # characters per chunk
    chunk_overlap: int     # character overlap between chunks
    top_k: int             # passages to retrieve
    rerank: bool           # whether to re-rank via LLM


RETRIEVAL_SETTINGS = [
    RetrievalSetting("small-5-no",   chunk_size=500,  chunk_overlap=50,  top_k=5,  rerank=False),
    RetrievalSetting("medium-3-no",  chunk_size=1000, chunk_overlap=100, top_k=3,  rerank=False),
    RetrievalSetting("medium-5-yes", chunk_size=1000, chunk_overlap=100, top_k=5,  rerank=True),
]
DEFAULT_RETRIEVAL = RETRIEVAL_SETTINGS[0]  # small-5-no

# ---------------------------------------------------------------------------
# Output File Paths & CSV Columns (Preserve exact required schema)
# ---------------------------------------------------------------------------
RESULTS_CSV = os.path.join(BASE_DIR, "results.csv")
CSV_COLUMNS = [
    "request_id", "scenario", "source", "start_time",
    "first_token_ms", "total_ms", "status", "retries",
    "tokens_in", "tokens_out", "retrieval_setting", "answer_grade",
]

# Companion Telemetry Paths
EXPERIMENTS_DIR = os.path.join(BASE_DIR, "experiments")
LOGS_DIR = os.path.join(EXPERIMENTS_DIR, "logs")
REPORTS_DIR = os.path.join(EXPERIMENTS_DIR, "reports")

REQUEST_EVENTS_CSV = os.path.join(LOGS_DIR, "request_events.csv")
SCENARIO_METADATA_JSON = os.path.join(LOGS_DIR, "scenario_metadata.json")
RETRIEVAL_DETAILS_JSON = os.path.join(REPORTS_DIR, "retrieval_evaluation_details.json")
QUOTA_STATE_JSON = os.path.join(LOGS_DIR, "quota_state.json")
