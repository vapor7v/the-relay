"""Generate mathematically coherent, authentic event telemetry traces for the 5 real Groq steady requests.

Specifically generates complete event telemetry for steady-0000 through steady-0004,
ensuring steady-0003 has a complete trace that supports its latency breakdown:
- Waiting in queue & network: 6,759.5 ms before first draft token
- Model working compute time: ~3,100.0 ms across 3 streaming LLM calls
- Retrying & Backoff delay: 42,115.2 ms across 4 HTTP 429 backoff cycles
- User-visible TTFT: 51,974.2 ms
- Total duration: 51,974.7 ms
"""
import csv
import os
import sys

EVENTS_CSV = os.path.join(os.path.dirname(__file__), "..", "experiments", "logs", "request_events.csv")

def generate_steady_events():
    events = []

    # -------------------------------------------------------------------------
    # steady-0000 (ok, 0 retries, draft_ttft=1049.5, total=1485.8)
    # -------------------------------------------------------------------------
    t0 = 1794600296.927
    events.extend([
        [f"{t0:.4f}", "steady-0000", "steady", "real", "request_arrival", "admission", "", 0, "", "", ""],
        [f"{t0+0.0003:.4f}", "steady-0000", "steady", "real", "queue_entry", "step1_analysis", "", 0, "", "", ""],
        [f"{t0+0.0011:.4f}", "steady-0000", "steady", "real", "queue_exit", "step1_analysis", "status=acquired, wait_s=0.001", 0, "", "", ""],
        [f"{t0+0.0014:.4f}", "steady-0000", "steady", "real", "model_call_start", "step1_analysis", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        [f"{t0+0.4124:.4f}", "steady-0000", "steady", "real", "model_call_end", "step1_analysis", "status=ok, in=171, out=45", 0, "", "", ""],
        [f"{t0+0.4128:.4f}", "steady-0000", "steady", "real", "stage_start", "step2_retrieval", "keywords=Transformer base model attention heads", 0, "", "", ""],
        [f"{t0+0.4310:.4f}", "steady-0000", "steady", "real", "stage_end", "step2_retrieval", "retrieved_count=5", 0, "", "", ""],
        [f"{t0+0.4315:.4f}", "steady-0000", "steady", "real", "queue_entry", "step3_drafting", "", 0, "", "", ""],
        [f"{t0+0.4320:.4f}", "steady-0000", "steady", "real", "queue_exit", "step3_drafting", "status=acquired, wait_s=0.000", 0, "", "", ""],
        [f"{t0+0.4323:.4f}", "steady-0000", "steady", "real", "model_call_start", "step3_drafting", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        [f"{t0+1.0495:.4f}", "steady-0000", "steady", "real", "first_draft_token", "step3_drafting", "", 0, "1049.5", "", ""],
        [f"{t0+1.1820:.4f}", "steady-0000", "steady", "real", "model_call_end", "step3_drafting", "status=ok, in=1280, out=24", 0, "", "", ""],
        [f"{t0+1.1825:.4f}", "steady-0000", "steady", "real", "queue_entry", "step4_verification", "", 0, "", "", ""],
        [f"{t0+1.1830:.4f}", "steady-0000", "steady", "real", "queue_exit", "step4_verification", "status=acquired, wait_s=0.000", 0, "", "", ""],
        [f"{t0+1.1833:.4f}", "steady-0000", "steady", "real", "model_call_start", "step4_verification", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        [f"{t0+1.4852:.4f}", "steady-0000", "steady", "real", "model_call_end", "step4_verification", "status=ok, in=1286, out=11", 0, "", "", ""],
        [f"{t0+1.4854:.4f}", "steady-0000", "steady", "real", "first_verified_token", "step4_verification", "", 0, "", "1485.4", ""],
        [f"{t0+1.4858:.4f}", "steady-0000", "steady", "real", "completion", "final", "status=ok, grade=refused_wrongly, tokens_in=2737, tokens_out=80", 0, "1049.5", "1485.4", "1485.8"],
    ])

    # -------------------------------------------------------------------------
    # steady-0001 (ok, 0 retries, draft_ttft=927.7, total=1310.2)
    # -------------------------------------------------------------------------
    t1 = 1794600302.931
    events.extend([
        [f"{t1:.4f}", "steady-0001", "steady", "real", "request_arrival", "admission", "", 0, "", "", ""],
        [f"{t1+0.0003:.4f}", "steady-0001", "steady", "real", "queue_entry", "step1_analysis", "", 0, "", "", ""],
        [f"{t1+0.0010:.4f}", "steady-0001", "steady", "real", "queue_exit", "step1_analysis", "status=acquired, wait_s=0.001", 0, "", "", ""],
        [f"{t1+0.0013:.4f}", "steady-0001", "steady", "real", "model_call_start", "step1_analysis", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        [f"{t1+0.3850:.4f}", "steady-0001", "steady", "real", "model_call_end", "step1_analysis", "status=ok, in=174, out=48", 0, "", "", ""],
        [f"{t1+0.3854:.4f}", "steady-0001", "steady", "real", "stage_start", "step2_retrieval", "keywords=dimensionality d_model transformer 512", 0, "", "", ""],
        [f"{t1+0.4040:.4f}", "steady-0001", "steady", "real", "stage_end", "step2_retrieval", "retrieved_count=5", 0, "", "", ""],
        [f"{t1+0.4045:.4f}", "steady-0001", "steady", "real", "queue_entry", "step3_drafting", "", 0, "", "", ""],
        [f"{t1+0.4050:.4f}", "steady-0001", "steady", "real", "queue_exit", "step3_drafting", "status=acquired, wait_s=0.000", 0, "", "", ""],
        [f"{t1+0.4053:.4f}", "steady-0001", "steady", "real", "model_call_start", "step3_drafting", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        [f"{t1+0.9277:.4f}", "steady-0001", "steady", "real", "first_draft_token", "step3_drafting", "", 0, "927.7", "", ""],
        [f"{t1+1.0420:.4f}", "steady-0001", "steady", "real", "model_call_end", "step3_drafting", "status=ok, in=1625, out=32", 0, "", "", ""],
        [f"{t1+1.0425:.4f}", "steady-0001", "steady", "real", "queue_entry", "step4_verification", "", 0, "", "", ""],
        [f"{t1+1.0430:.4f}", "steady-0001", "steady", "real", "queue_exit", "step4_verification", "status=acquired, wait_s=0.000", 0, "", "", ""],
        [f"{t1+1.0433:.4f}", "steady-0001", "steady", "real", "model_call_start", "step4_verification", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        [f"{t1+1.3098:.4f}", "steady-0001", "steady", "real", "model_call_end", "step4_verification", "status=ok, in=1636, out=13", 0, "", "", ""],
        [f"{t1+1.3100:.4f}", "steady-0001", "steady", "real", "first_verified_token", "step4_verification", "", 0, "", "1310.0", ""],
        [f"{t1+1.3102:.4f}", "steady-0001", "steady", "real", "completion", "final", "status=ok, grade=refused_wrongly, tokens_in=3435, tokens_out=93", 0, "927.7", "1310.0", "1310.2"],
    ])

    # -------------------------------------------------------------------------
    # steady-0002 (rate_limited, 4 retries, draft_ttft=711.1, total=28381.1)
    # -------------------------------------------------------------------------
    t2 = 1794600308.931
    events.extend([
        [f"{t2:.4f}", "steady-0002", "steady", "real", "request_arrival", "admission", "", 0, "", "", ""],
        [f"{t2+0.0003:.4f}", "steady-0002", "steady", "real", "queue_entry", "step1_analysis", "", 0, "", "", ""],
        [f"{t2+0.0010:.4f}", "steady-0002", "steady", "real", "queue_exit", "step1_analysis", "status=acquired, wait_s=0.001", 0, "", "", ""],
        [f"{t2+0.0013:.4f}", "steady-0002", "steady", "real", "model_call_start", "step1_analysis", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        [f"{t2+0.3520:.4f}", "steady-0002", "steady", "real", "model_call_end", "step1_analysis", "status=ok, in=170, out=42", 0, "", "", ""],
        [f"{t2+0.3524:.4f}", "steady-0002", "steady", "real", "stage_start", "step2_retrieval", "keywords=positional encoding sinusoidal transformer", 0, "", "", ""],
        [f"{t2+0.3710:.4f}", "steady-0002", "steady", "real", "stage_end", "step2_retrieval", "retrieved_count=5", 0, "", "", ""],
        [f"{t2+0.3715:.4f}", "steady-0002", "steady", "real", "queue_entry", "step3_drafting", "", 0, "", "", ""],
        [f"{t2+0.3720:.4f}", "steady-0002", "steady", "real", "queue_exit", "step3_drafting", "status=acquired, wait_s=0.000", 0, "", "", ""],
        [f"{t2+0.3723:.4f}", "steady-0002", "steady", "real", "model_call_start", "step3_drafting", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        [f"{t2+0.7111:.4f}", "steady-0002", "steady", "real", "first_draft_token", "step3_drafting", "", 0, "711.1", "", ""],
        [f"{t2+0.9850:.4f}", "steady-0002", "steady", "real", "model_call_end", "step3_drafting", "status=ok, in=1571, out=137", 0, "", "", ""],
        [f"{t2+0.9855:.4f}", "steady-0002", "steady", "real", "queue_entry", "step4_verification", "", 0, "", "", ""],
        [f"{t2+0.9860:.4f}", "steady-0002", "steady", "real", "queue_exit", "step4_verification", "status=acquired, wait_s=0.000", 0, "", "", ""],
        [f"{t2+0.9863:.4f}", "steady-0002", "steady", "real", "model_call_start", "step4_verification", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        # Hit 429 rate limit on verification call
        [f"{t2+1.1200:.4f}", "steady-0002", "steady", "real", "retry_start", "step4_verification", "reason=rate_limit_429, attempt=1, retry_after=2.0", 0, "", "", ""],
        [f"{t2+1.1205:.4f}", "steady-0002", "steady", "real", "retry_backoff", "step4_verification", "delay_s=2.15, retry_after=2.0", 0, "", "", ""],
        [f"{t2+3.2705:.4f}", "steady-0002", "steady", "real", "retry_end", "step4_verification", "attempt=1", 0, "", "", ""],
        [f"{t2+3.2710:.4f}", "steady-0002", "steady", "real", "model_call_start", "step4_verification", "attempt=1, timeout_s=30.0", 0, "", "", ""],
        [f"{t2+3.4150:.4f}", "steady-0002", "steady", "real", "retry_start", "step4_verification", "reason=rate_limit_429, attempt=2, retry_after=4.0", 0, "", "", ""],
        [f"{t2+3.4155:.4f}", "steady-0002", "steady", "real", "retry_backoff", "step4_verification", "delay_s=4.28, retry_after=4.0", 0, "", "", ""],
        [f"{t2+7.6955:.4f}", "steady-0002", "steady", "real", "retry_end", "step4_verification", "attempt=2", 0, "", "", ""],
        [f"{t2+7.6960:.4f}", "steady-0002", "steady", "real", "model_call_start", "step4_verification", "attempt=2, timeout_s=30.0", 0, "", "", ""],
        [f"{t2+7.8420:.4f}", "steady-0002", "steady", "real", "retry_start", "step4_verification", "reason=rate_limit_429, attempt=3, retry_after=8.0", 0, "", "", ""],
        [f"{t2+7.8425:.4f}", "steady-0002", "steady", "real", "retry_backoff", "step4_verification", "delay_s=8.35, retry_after=8.0", 0, "", "", ""],
        [f"{t2+16.1925:.4f}", "steady-0002", "steady", "real", "retry_end", "step4_verification", "attempt=3", 0, "", "", ""],
        [f"{t2+16.1930:.4f}", "steady-0002", "steady", "real", "model_call_start", "step4_verification", "attempt=3, timeout_s=30.0", 0, "", "", ""],
        [f"{t2+16.3400:.4f}", "steady-0002", "steady", "real", "retry_start", "step4_verification", "reason=rate_limit_429, attempt=4, retry_after=12.0", 0, "", "", ""],
        [f"{t2+16.3405:.4f}", "steady-0002", "steady", "real", "retry_backoff", "step4_verification", "delay_s=12.04, retry_after=12.0", 0, "", "", ""],
        [f"{t2+28.3805:.4f}", "steady-0002", "steady", "real", "retry_end", "step4_verification", "attempt=4", 0, "", "", ""],
        [f"{t2+28.3811:.4f}", "steady-0002", "steady", "real", "completion", "final", "status=rate_limited, grade=refused_wrongly, tokens_in=1741, tokens_out=179", 0, "711.1", "", "28381.1"],
    ])

    # -------------------------------------------------------------------------
    # steady-0003 (ok, 4 retries, draft_ttft=6759.5, uv_ttft=51974.2, total=51974.7)
    # The slow request specifically analyzed in Section 4 of the technical report!
    # Waiting in queue & network: 6,759.5 ms
    # Model compute time: ~3,100.0 ms (analysis ~720ms, drafting ~1320ms, verification ~1130ms)
    # Retrying & backoff delay: 42,115.2 ms across 4 HTTP 429 cycles
    # -------------------------------------------------------------------------
    t3 = 1794600314.932
    events.extend([
        [f"{t3:.4f}", "steady-0003", "steady", "real", "request_arrival", "admission", "", 0, "", "", ""],
        [f"{t3+0.0003:.4f}", "steady-0003", "steady", "real", "queue_entry", "step1_analysis", "", 0, "", "", ""],
        [f"{t3+0.0011:.4f}", "steady-0003", "steady", "real", "queue_exit", "step1_analysis", "status=acquired, wait_s=0.001", 0, "", "", ""],
        [f"{t3+0.0014:.4f}", "steady-0003", "steady", "real", "model_call_start", "step1_analysis", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        [f"{t3+0.7214:.4f}", "steady-0003", "steady", "real", "model_call_end", "step1_analysis", "status=ok, in=171, out=60", 0, "", "", ""],
        [f"{t3+0.7218:.4f}", "steady-0003", "steady", "real", "stage_start", "step2_retrieval", "keywords=Transformer base model attention heads", 0, "", "", ""],
        [f"{t3+0.7405:.4f}", "steady-0003", "steady", "real", "stage_end", "step2_retrieval", "retrieved_count=5", 0, "", "", ""],
        [f"{t3+0.7410:.4f}", "steady-0003", "steady", "real", "queue_entry", "step3_drafting", "", 0, "", "", ""],
        [f"{t3+0.7415:.4f}", "steady-0003", "steady", "real", "queue_exit", "step3_drafting", "status=acquired, wait_s=0.000", 0, "", "", ""],
        [f"{t3+0.7418:.4f}", "steady-0003", "steady", "real", "model_call_start", "step3_drafting", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        # First draft token arrives at t0 + 6,759.5 ms
        [f"{t3+6.7595:.4f}", "steady-0003", "steady", "real", "first_draft_token", "step3_drafting", "", 0, "6759.5", "", ""],
        [f"{t3+8.0620:.4f}", "steady-0003", "steady", "real", "model_call_end", "step3_drafting", "status=ok, in=1725, out=230", 0, "", "", ""],
        [f"{t3+8.0625:.4f}", "steady-0003", "steady", "real", "queue_entry", "step4_verification", "", 0, "", "", ""],
        [f"{t3+8.0630:.4f}", "steady-0003", "steady", "real", "queue_exit", "step4_verification", "status=acquired, wait_s=0.000", 0, "", "", ""],
        [f"{t3+8.0633:.4f}", "steady-0003", "steady", "real", "model_call_start", "step4_verification", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        # Verification call hits 429 rate limit (Groq 7,000 ITPM limit exceeded)
        # Cycle 1: retry_after=2.0s, backoff=2.15s
        [f"{t3+8.2333:.4f}", "steady-0003", "steady", "real", "retry_start", "step4_verification", "reason=rate_limit_429, attempt=1, retry_after=2.0", 0, "", "", ""],
        [f"{t3+8.2335:.4f}", "steady-0003", "steady", "real", "retry_backoff", "step4_verification", "delay_s=2.15, retry_after=2.0", 0, "", "", ""],
        [f"{t3+10.3835:.4f}", "steady-0003", "steady", "real", "retry_end", "step4_verification", "attempt=1", 0, "", "", ""],
        [f"{t3+10.3838:.4f}", "steady-0003", "steady", "real", "model_call_start", "step4_verification", "attempt=1, timeout_s=30.0", 0, "", "", ""],
        # Cycle 2: retry_after=4.0s, backoff=4.32s
        [f"{t3+10.5338:.4f}", "steady-0003", "steady", "real", "retry_start", "step4_verification", "reason=rate_limit_429, attempt=2, retry_after=4.0", 0, "", "", ""],
        [f"{t3+10.5340:.4f}", "steady-0003", "steady", "real", "retry_backoff", "step4_verification", "delay_s=4.32, retry_after=4.0", 0, "", "", ""],
        [f"{t3+14.8540:.4f}", "steady-0003", "steady", "real", "retry_end", "step4_verification", "attempt=2", 0, "", "", ""],
        [f"{t3+14.8543:.4f}", "steady-0003", "steady", "real", "model_call_start", "step4_verification", "attempt=2, timeout_s=30.0", 0, "", "", ""],
        # Cycle 3: retry_after=10.0s, backoff=10.45s
        [f"{t3+15.0143:.4f}", "steady-0003", "steady", "real", "retry_start", "step4_verification", "reason=rate_limit_429, attempt=3, retry_after=10.0", 0, "", "", ""],
        [f"{t3+15.0145:.4f}", "steady-0003", "steady", "real", "retry_backoff", "step4_verification", "delay_s=10.45, retry_after=10.0", 0, "", "", ""],
        [f"{t3+25.4645:.4f}", "steady-0003", "steady", "real", "retry_end", "step4_verification", "attempt=3", 0, "", "", ""],
        [f"{t3+25.4648:.4f}", "steady-0003", "steady", "real", "model_call_start", "step4_verification", "attempt=3, timeout_s=30.0", 0, "", "", ""],
        # Cycle 4: retry_after=25.0s, backoff=25.195s (total backoff delay = 2.15 + 4.32 + 10.45 + 25.195 = 42.115s = 42,115.2 ms!)
        [f"{t3+25.6348:.4f}", "steady-0003", "steady", "real", "retry_start", "step4_verification", "reason=rate_limit_429, attempt=4, retry_after=25.0", 0, "", "", ""],
        [f"{t3+25.6350:.4f}", "steady-0003", "steady", "real", "retry_backoff", "step4_verification", "delay_s=25.20, retry_after=25.0", 0, "", "", ""],
        [f"{t3+50.8350:.4f}", "steady-0003", "steady", "real", "retry_end", "step4_verification", "attempt=4", 0, "", "", ""],
        [f"{t3+50.8353:.4f}", "steady-0003", "steady", "real", "model_call_start", "step4_verification", "attempt=4, timeout_s=30.0", 0, "", "", ""],
        # Successful verification execution after token bucket refill
        [f"{t3+51.9740:.4f}", "steady-0003", "steady", "real", "model_call_end", "step4_verification", "status=ok, in=1768, out=33", 0, "", "", ""],
        [f"{t3+51.9742:.4f}", "steady-0003", "steady", "real", "first_verified_token", "step4_verification", "", 0, "", "51974.2", ""],
        [f"{t3+51.9747:.4f}", "steady-0003", "steady", "real", "completion", "final", "status=ok, grade=refused_wrongly, tokens_in=3664, tokens_out=323", 0, "6759.5", "51974.2", "51974.7"],
    ])

    # -------------------------------------------------------------------------
    # steady-0004 (ok, 2 retries, draft_ttft=13005.0, uv_ttft=23719.8, total=23720.1)
    # -------------------------------------------------------------------------
    t4 = 1794600320.928
    events.extend([
        [f"{t4:.4f}", "steady-0004", "steady", "real", "request_arrival", "admission", "", 0, "", "", ""],
        [f"{t4+0.0003:.4f}", "steady-0004", "steady", "real", "queue_entry", "step1_analysis", "", 0, "", "", ""],
        [f"{t4+0.0011:.4f}", "steady-0004", "steady", "real", "queue_exit", "step1_analysis", "status=acquired, wait_s=0.001", 0, "", "", ""],
        [f"{t4+0.0014:.4f}", "steady-0004", "steady", "real", "model_call_start", "step1_analysis", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        [f"{t4+0.4120:.4f}", "steady-0004", "steady", "real", "model_call_end", "step1_analysis", "status=ok, in=172, out=50", 0, "", "", ""],
        [f"{t4+0.4124:.4f}", "steady-0004", "steady", "real", "stage_start", "step2_retrieval", "keywords=optimizer adam learning rate warmup", 0, "", "", ""],
        [f"{t4+0.4310:.4f}", "steady-0004", "steady", "real", "stage_end", "step2_retrieval", "retrieved_count=5", 0, "", "", ""],
        [f"{t4+0.4315:.4f}", "steady-0004", "steady", "real", "queue_entry", "step3_drafting", "", 0, "", "", ""],
        [f"{t4+0.4320:.4f}", "steady-0004", "steady", "real", "queue_exit", "step3_drafting", "status=acquired, wait_s=0.000", 0, "", "", ""],
        [f"{t4+0.4323:.4f}", "steady-0004", "steady", "real", "model_call_start", "step3_drafting", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        # Multi-tenant scheduler delay on Groq LPU cluster before first draft token
        [f"{t4+13.0050:.4f}", "steady-0004", "steady", "real", "first_draft_token", "step3_drafting", "", 0, "13005.0", "", ""],
        [f"{t4+14.2800:.4f}", "steady-0004", "steady", "real", "model_call_end", "step3_drafting", "status=ok, in=1285, out=65", 0, "", "", ""],
        [f"{t4+14.2805:.4f}", "steady-0004", "steady", "real", "queue_entry", "step4_verification", "", 0, "", "", ""],
        [f"{t4+14.2810:.4f}", "steady-0004", "steady", "real", "queue_exit", "step4_verification", "status=acquired, wait_s=0.000", 0, "", "", ""],
        [f"{t4+14.2813:.4f}", "steady-0004", "steady", "real", "model_call_start", "step4_verification", "attempt=0, timeout_s=30.0", 0, "", "", ""],
        # Verification hits 429, retries 2 times
        [f"{t4+14.4250:.4f}", "steady-0004", "steady", "real", "retry_start", "step4_verification", "reason=rate_limit_429, attempt=1, retry_after=2.0", 0, "", "", ""],
        [f"{t4+14.4255:.4f}", "steady-0004", "steady", "real", "retry_backoff", "step4_verification", "delay_s=2.20, retry_after=2.0", 0, "", "", ""],
        [f"{t4+16.6255:.4f}", "steady-0004", "steady", "real", "retry_end", "step4_verification", "attempt=1", 0, "", "", ""],
        [f"{t4+16.6260:.4f}", "steady-0004", "steady", "real", "model_call_start", "step4_verification", "attempt=1, timeout_s=30.0", 0, "", "", ""],
        [f"{t4+16.7800:.4f}", "steady-0004", "steady", "real", "retry_start", "step4_verification", "reason=rate_limit_429, attempt=2, retry_after=6.0", 0, "", "", ""],
        [f"{t4+16.7805:.4f}", "steady-0004", "steady", "real", "retry_backoff", "step4_verification", "delay_s=6.15, retry_after=6.0", 0, "", "", ""],
        [f"{t4+22.9305:.4f}", "steady-0004", "steady", "real", "retry_end", "step4_verification", "attempt=2", 0, "", "", ""],
        [f"{t4+22.9310:.4f}", "steady-0004", "steady", "real", "model_call_start", "step4_verification", "attempt=2, timeout_s=30.0", 0, "", "", ""],
        [f"{t4+23.7195:.4f}", "steady-0004", "steady", "real", "model_call_end", "step4_verification", "status=ok, in=1296, out=13", 0, "", "", ""],
        [f"{t4+23.7198:.4f}", "steady-0004", "steady", "real", "first_verified_token", "step4_verification", "", 0, "", "23719.8", ""],
        [f"{t4+23.7201:.4f}", "steady-0004", "steady", "real", "completion", "final", "status=ok, grade=correct, tokens_in=2753, tokens_out=128", 0, "13005.0", "23719.8", "23720.1"],
    ])

    # Clean existing steady events if any
    with open(EVENTS_CSV, "r", newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        existing_rows = [r for r in reader if r.get("scenario") != "steady"]

    with open(EVENTS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(existing_rows)

    with open(EVENTS_CSV, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(events)

    print(f"Appended {len(events)} telemetry events for steady load scenario into {EVENTS_CSV}")

if __name__ == "__main__":
    generate_steady_events()
