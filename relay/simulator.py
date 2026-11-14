"""Stand-in model server calibrated from real Groq measurements.

A local HTTP server that mimics Groq's API behavior:
- Calibrated latency (log-normal distribution matching Groq pilot measurements)
- Streaming token-by-token SSE delivery
- Rate limit simulation (HTTP 429 with retry-after header and standard error payload)
- Load-dependent slowdown with bounded concurrency degradation
- Controlled failure injection and daily quota exhaustion
- Context-aware protocol responses (Query Analysis JSON, Answer Drafting, Citation Verification)
- Thread-safe concurrency accounting and deterministic random seeding
"""
import asyncio
import json
import math
import os
import random
import re
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional, Tuple, Dict, Any, List
import threading

CALIBRATION_FILE = os.path.join(os.path.dirname(__file__), "calibration.json")

DEFAULT_CALIBRATION = {
    "ttft_median_ms": 284.0,         # Median time to first token
    "ttft_p95_ms": 1407.5,           # 95th percentile TTFT
    "ttft_stddev_log": 0.9731,       # Log-normal sigma matching empirical p95 from median
    "ttft_sample_stddev_log": 0.679, # Raw sample stddev of log(TTFT) from 10 pilot runs
    "tps": 520.0,                    # Tokens per second
    "tps_stddev": 135.0,             # Stddev for TPS
    "rpm_limit": 30,
    "tpm_limit": 8000,
    "rpd_limit": 1000,
    "tpd_limit": 200000,
    "failure_rate": 0.01,            # 1% transient failure
    "load_slowdown_factor": 15.0,    # Extra TTFT ms per concurrent in-flight request
}


def load_calibration() -> dict:
    if os.path.exists(CALIBRATION_FILE):
        try:
            with open(CALIBRATION_FILE, "r") as f:
                data = json.load(f)
                res = DEFAULT_CALIBRATION.copy()
                res.update(data)
                return res
        except Exception:
            pass
    return DEFAULT_CALIBRATION.copy()


class SimulatorState:
    """Shared thread-safe state for the stand-in simulator."""

    def __init__(self, cal: dict, seed: Optional[int] = None):
        self.cal = cal
        self.rng = random.Random(seed) if seed is not None else random.Random()
        self.lock = threading.Lock()
        self.request_count_minute = 0
        self.token_count_minute = 0
        self.minute_start = time.time()
        self.day_start = time.time()
        self.request_count_day = 0
        self.token_count_day = 0
        self.concurrent = 0
        self.total_requests = 0

    def check_rate_limit(self, estimated_tokens: int = 500) -> Optional[float]:
        """Check rate limits. Returns retry-after seconds or None if OK."""
        now = time.time()
        with self.lock:
            # Daily reset (24h or midnight simulation)
            if now - self.day_start >= 86400:
                self.request_count_day = 0
                self.token_count_day = 0
                self.day_start = now

            # Daily limit check
            rpd_lim = self.cal.get("rpd_limit", 14400)
            tpd_lim = self.cal.get("tpd_limit", 500000)
            if self.request_count_day >= rpd_lim or (self.token_count_day + estimated_tokens) > tpd_lim:
                return max(1.0, 86400.0 - (now - self.day_start))

            # Minute reset
            if now - self.minute_start >= 60.0:
                self.request_count_minute = 0
                self.token_count_minute = 0
                self.minute_start = now

            if self.request_count_minute >= self.cal.get("rpm_limit", 60):
                return max(1.0, 60.0 - (now - self.minute_start))
            if (self.token_count_minute + estimated_tokens) > self.cal.get("tpm_limit", 7000):
                return max(1.0, 60.0 - (now - self.minute_start))

            # Consume capacity and track concurrency
            self.request_count_minute += 1
            self.token_count_minute += estimated_tokens
            self.request_count_day += 1
            self.token_count_day += estimated_tokens
            self.concurrent += 1
            self.total_requests += 1
            return None

    def release(self):
        """Release concurrent in-flight slot safely."""
        with self.lock:
            self.concurrent = max(0, self.concurrent - 1)

    def sample_ttft(self) -> float:
        """Sample TTFT from calibrated log-normal distribution with load factor."""
        median = self.cal["ttft_median_ms"]
        sigma = self.cal["ttft_stddev_log"]
        mu = math.log(median)
        with self.lock:
            base = self.rng.lognormvariate(mu, sigma)
            conc = self.concurrent
        load_extra = conc * self.cal["load_slowdown_factor"]
        return max(50.0, base + load_extra)

    def sample_tps(self) -> float:
        """Sample tokens per second, bounded strictly positive."""
        with self.lock:
            raw_tps = max(50.0, self.rng.gauss(self.cal["tps"], self.cal["tps_stddev"]))
            conc = self.concurrent
        # Clamped degradation: between 30% and 100% of base speed
        load_factor = max(0.3, 1.0 - conc * 0.05)
        return max(15.0, raw_tps * load_factor)

    def should_fail(self) -> bool:
        with self.lock:
            return self.rng.random() < self.cal.get("failure_rate", 0.01)


def _extract_question_from_prompt(prompt: str) -> str:
    """Extract only the user's question from a pipeline prompt."""
    # Check for QUESTION: ... marker
    m = re.search(r'QUESTION:\s*(.*?)(?:\n\s*ANSWER:|\Z)', prompt, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Check for Question: ... marker in Query Analysis
    m2 = re.search(r'Question:\s*(.*?)(?:\Z)', prompt, re.DOTALL | re.IGNORECASE)
    if m2:
        return m2.group(1).strip()
    return prompt.strip()


def generate_response_text(messages: List[Dict[str, str]], prompt_tokens: int = 100) -> Tuple[str, int]:
    """Generate realistic, context-aware responses matching pipeline protocols."""
    content = ""
    for m in messages:
        content += m.get("content", "") + "\n"

    # 1. Step 1: Query Analysis Prompt
    if "You are a research assistant. Analyze this question" in content:
        q_text = _extract_question_from_prompt(content).lower()
        if any(w in q_text for w in ["france", "gpt-4", "environmental", "weather", "president", "tokyo"]):
            resp = json.dumps({
                "answerable": False,
                "keywords": [],
                "reasoning": "Topic not covered in the three research papers."
            })
        else:
            # Extract discriminative keywords for the question
            keywords = []
            if "attention heads" in q_text:
                keywords = ["attention", "heads", "transformer", "base", "model"]
            elif "dimensionality" in q_text or "d_model" in q_text:
                keywords = ["dimensionality", "d_model", "transformer", "512"]
            elif "positional encoding" in q_text:
                keywords = ["positional", "encoding", "sinusoidal", "transformer"]
            elif "optimizer" in q_text:
                keywords = ["optimizer", "adam", "learning", "rate", "warmup"]
            elif "bleu" in q_text:
                keywords = ["bleu", "score", "wmt", "english", "german"]
            elif "codec" in q_text or "bitrate" in q_text:
                keywords = ["mimi", "audio", "codec", "bitrate", "moshi"]
            elif "full-duplex" in q_text or "duplex" in q_text:
                keywords = ["full-duplex", "inner", "monologue", "moshi", "audio"]
            elif "latency" in q_text:
                keywords = ["theoretical", "latency", "moshi", "algorithmic", "frame"]
            elif "training data" in q_text:
                keywords = ["training", "data", "fisher", "synthetic", "moshi"]
            elif "parameters" in q_text:
                keywords = ["parameters", "backbone", "helium", "moshi", "7b"]
            elif "dynamic chunking" in q_text and ("problem" in q_text or "fixed" in q_text):
                keywords = ["dynamic", "chunking", "fixed-size", "boundaries", "rigidity"]
            elif "datasets were used" in q_text or "evaluation" in q_text:
                keywords = ["datasets", "lra", "benchmarks", "dynamic", "chunking"]
            elif "chunk boundaries" in q_text:
                keywords = ["chunk", "boundaries", "predictor", "gate", "learned"]
            elif "regularization" in q_text:
                keywords = ["regularization", "dropout", "label", "smoothing", "transformer"]
            elif "differ" in q_text and "attention" in q_text:
                keywords = ["attention", "transformer", "moshi", "cross-attention"]
            else:
                keywords = ["transformer", "architecture", "attention", "mechanism"]

            resp = json.dumps({
                "answerable": True,
                "keywords": keywords,
                "reasoning": "Topic is directly addressed in the research corpus."
            })
        return resp, max(20, len(resp) // 4)

    # 2. Step 4: Citation Verification Prompt
    if "You are a citation verifier" in content:
        # Check if the answer contains any citations
        m_ans = re.search(r'ANSWER TO CHECK:\s*(.*?)(?:\Z)', content, re.DOTALL)
        ans_text = m_ans.group(1).strip() if m_ans else content

        has_bracket = "[" in ans_text and "]" in ans_text
        has_paper = any(p in ans_text for p in ["Attention Is All You Need", "Moshi", "Dynamic Chunking"])
        has_page = "p." in ans_text.lower() or "pp." in ans_text.lower()

        if has_bracket and has_paper and has_page:
            resp = json.dumps({"valid": True, "issues": []})
        else:
            resp = json.dumps({
                "valid": False,
                "issues": ["Citation missing required paper title or exact page reference."]
            })
        return resp, max(15, len(resp) // 4)

    # 3. Step 3: Answer Drafting Prompt
    q_target = _extract_question_from_prompt(content).lower()

    if "attention heads" in q_target:
        resp = "The Transformer base model uses 8 attention heads with dimensionality d_k = d_v = 64 [Attention Is All You Need, p.5]."
    elif "dimensionality" in q_target or "d_model" in q_target:
        resp = "The dimensionality of the model (d_model) in the Transformer base model is 512 [Attention Is All You Need, p.5]."
    elif "positional encoding" in q_target:
        resp = "The Transformer uses sinusoidal positional encodings generated via sine and cosine functions [Attention Is All You Need, p.6]."
    elif "optimizer" in q_target:
        resp = "They used the Adam optimizer with beta1=0.9, beta2=0.98, and a warmup learning rate schedule [Attention Is All You Need, p.7]."
    elif "bleu" in q_target:
        resp = "The Transformer big model achieved an English-to-German score of 28.4 BLEU on WMT 2014 [Attention Is All You Need, p.8]."
    elif "codec" in q_target or "bitrate" in q_target:
        resp = "Moshi uses the Mimi neural audio codec operating at 1.1 kbps [Moshi: a speech-text foundation model for real-time dialogue, p.3]."
    elif "full-duplex" in q_target or "simultaneous" in q_target:
        resp = "Moshi supports full-duplex conversation using an Inner Monologue mechanism with parallel audio streams [Moshi: a speech-text foundation model for real-time dialogue, p.2]."
    elif "latency" in q_target:
        resp = "The theoretical latency of the Moshi system is approximately 200ms with a 160ms algorithmic frame size [Moshi: a speech-text foundation model for real-time dialogue, p.1]."
    elif "training data" in q_target:
        resp = "The Moshi model was trained on conversational speech including the Fisher dataset and synthetic dialogue audio [Moshi: a speech-text foundation model for real-time dialogue, p.5]."
    elif "parameters" in q_target:
        resp = "The Moshi language model backbone has 7B parameters based on the Helium-7B architecture [Moshi: a speech-text foundation model for real-time dialogue, p.4]."
    elif "dynamic chunking" in q_target and ("problem" in q_target or "fixed" in q_target):
        resp = "Dynamic chunking solves the rigidity of fixed-size chunking by learning variable-length sequence boundaries [Dynamic Chunking for End-to-End Hierarchical Sequence Modeling, p.2]."
    elif "datasets were used" in q_target or "evaluate" in q_target:
        resp = "The dynamic chunking model was evaluated on Long Range Arena (LRA) benchmarks and language modeling datasets [Dynamic Chunking for End-to-End Hierarchical Sequence Modeling, p.6]."
    elif "chunk boundaries" in q_target:
        resp = "The model decides chunk boundaries using a learned boundary predictor that dynamically predicts boundary gates [Dynamic Chunking for End-to-End Hierarchical Sequence Modeling, p.3]."
    elif "regularization" in q_target:
        resp = "The Transformer model uses residual dropout and label smoothing for regularization [Attention Is All You Need, p.7]."
    elif "differ" in q_target and "attention" in q_target:
        resp = "All three papers utilize attention mechanisms: Transformer introduces multi-head self-attention, and Moshi adapts it to temporal cross-attention [Attention Is All You Need, p.4; Moshi: a speech-text foundation model for real-time dialogue, p.3]."
    else:
        resp = "Based on the passages, the Transformer architecture utilizes multi-head attention mechanisms and feed-forward sublayers [Attention Is All You Need, p.2]."

    return resp, max(25, len(resp) // 4)


class SimulatorHandler(BaseHTTPRequestHandler):
    """HTTP handler for the stand-in simulator mimicking Groq API streaming responses."""

    state: SimulatorState = None

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404, "Endpoint not found")
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode(errors="replace")

        try:
            request = json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON body")
            return

        is_stream = request.get("stream", False)
        max_tokens = request.get("max_tokens", 1024)

        messages = request.get("messages", [])
        prompt_text = " ".join(m.get("content", "") for m in messages)
        prompt_tokens = max(20, len(prompt_text) // 4)
        estimated_req_tokens = prompt_tokens + min(max_tokens, 300)

        # Rate limit check
        retry_after = self.state.check_rate_limit(estimated_req_tokens)
        if retry_after is not None:
            self.send_response(429)
            self.send_header("Content-Type", "application/json")
            self.send_header("retry-after", str(int(math.ceil(retry_after))))
            self.send_header("x-ratelimit-limit-requests", str(self.state.cal.get("rpd_limit", 1000)))
            self.send_header("x-ratelimit-limit-tokens", str(self.state.cal.get("tpm_limit", 8000)))
            self.send_header("x-ratelimit-remaining-tokens", "0")
            self.send_header("x-ratelimit-reset-tokens", f"{int(math.ceil(retry_after))}s")
            self.end_headers()
            error_body = json.dumps({
                "error": {
                    "message": f"Rate limit reached on input tokens per minute (ITPM): Limit {self.state.cal.get('tpm_limit', 8000)}. Please try again in {int(retry_after)}s.",
                    "type": "tokens",
                    "code": "rate_limit_exceeded",
                }
            })
            self.wfile.write(error_body.encode())
            return

        # Ensure in-flight concurrency slot is always released on normal exit, client disconnect, or cancellation
        try:
            if self.state.should_fail():
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": {"message": "Simulated upstream 500 internal error"}}).encode())
                return

            response_text, completion_tokens = generate_response_text(messages, prompt_tokens)

            # Calibrated TTFT delay
            ttft_ms = self.state.sample_ttft()
            time.sleep(ttft_ms / 1000.0)

            if is_stream:
                self._stream_response(request, response_text, completion_tokens, prompt_tokens)
            else:
                self._single_response(request, response_text, completion_tokens, prompt_tokens)
        finally:
            self.state.release()

    def _stream_response(self, request, text: str, completion_tokens: int, prompt_tokens: int):
        """Send streaming SSE response matching Groq's exact chunk format."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("x-ratelimit-limit-requests", str(self.state.cal.get("rpd_limit", 1000)))
        self.send_header("x-ratelimit-limit-tokens", str(self.state.cal.get("tpm_limit", 8000)))
        self.end_headers()

        chat_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
        model = request.get("model", "qwen/qwen3.8-27b")
        tps = self.state.sample_tps()

        words = text.split(" ")
        tokens = [w + " " for w in words[:-1]] + [words[-1]]

        for i, token in enumerate(tokens):
            chunk = {
                "id": chat_id,
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model,
                "choices": [{
                    "index": 0,
                    "delta": {"content": token} if i > 0 else {"role": "assistant", "content": token},
                    "finish_reason": None,
                }],
            }
            line = f"data: {json.dumps(chunk)}\n\n"
            try:
                self.wfile.write(line.encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                return

            if i < len(tokens) - 1:
                delay = 1.0 / tps
                time.sleep(delay)

        final = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "delta": {},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        try:
            self.wfile.write(f"data: {json.dumps(final)}\n\n".encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _single_response(self, request, text: str, completion_tokens: int, prompt_tokens: int):
        tps = self.state.sample_tps()
        gen_time = completion_tokens / tps
        time.sleep(gen_time)

        response = {
            "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": request.get("model", "qwen/qwen3.8-27b"),
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        }
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())


_global_server = None
_global_thread = None
_global_state = None


def run_simulator(port: int = 8787, seed: Optional[int] = None) -> HTTPServer:
    """Start simulator in-process on background daemon thread."""
    global _global_server, _global_thread, _global_state

    if _global_server is not None:
        if seed is not None and _global_state is not None:
            _global_state.rng = random.Random(seed)
        return _global_server

    cal = load_calibration()
    _global_state = SimulatorState(cal, seed=seed)

    class CustomHandler(SimulatorHandler):
        state = _global_state

    server = HTTPServer(("127.0.0.1", port), CustomHandler)
    _global_server = server

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    _global_thread = thread
    time.sleep(0.1)
    return server
