"""LLM client for Groq API with streaming support and end-to-end deadline enforcement.

Key features:
- Streaming response for microsecond-precision TTFT measurement
- Strict detection of first actual generated content token (ignoring metadata events)
- Shared end-to-end pipeline deadline propagation across all calls and retry loops
- Immediate rejection of non-retryable client errors (400, 401, 403, 404)
- Bounded exponential backoff with full jitter respecting remaining deadline
- Monotonic clock timing without artificial timestamp clamping
"""
import asyncio
import json
import time
import random
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import httpx

from config import (
    get_groq_api_key, GROQ_BASE_URL, GROQ_MODEL,
    SIMULATOR_URL, API_TIMEOUT_S,
    MAX_LLM_RETRIES, RETRY_BASE_DELAY_S, RETRY_MAX_DELAY_S,
)


@dataclass
class LLMResponse:
    """Result of a single LLM interaction."""
    text: str
    first_token_time_ms: Optional[float]   # ms from request start to first content token
    total_time_ms: float                   # ms from request start to completion
    tokens_in: int
    tokens_out: int
    retries: int
    status: str                            # "ok", "rate_limited", "timeout", "error"
    first_token_monotonic: Optional[float] = None  # Monotonic timestamp of first content token
    headers: Optional[Dict[str, str]] = None       # Captured response headers for rate limit telemetry


class RateLimitError(Exception):
    def __init__(self, retry_after: Optional[float] = None, body: str = "", headers: Optional[Dict[str, str]] = None):
        self.retry_after = retry_after
        self.body = body
        self.headers = headers or {}
        super().__init__(f"Rate limited (retry_after={retry_after}): {body[:100]}")


class NonRetryableError(Exception):
    """Errors that should never be retried (400, 401, 403, 404)."""
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"Non-retryable HTTP {status_code}: {message}")


class LLMError(Exception):
    """Generic LLM error, potentially retryable (5xx, network drops)."""
    pass


class LLMClient:
    """Async LLM client with streaming, shared deadlines, and robust retries."""

    def __init__(self, use_simulator: bool = False, api_key: Optional[str] = None):
        self.use_simulator = use_simulator
        if use_simulator:
            self.api_key = api_key or "sim-key"
            self.base_url = SIMULATOR_URL
        else:
            self.api_key = api_key or get_groq_api_key()
            self.base_url = GROQ_BASE_URL
        self.model = GROQ_MODEL
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(API_TIMEOUT_S, connect=10.0),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 1024,
        deadline: Optional[float] = None,
        stage: str = "llm_call",
        on_event: Optional[Any] = None,
    ) -> LLMResponse:
        """Send a streaming chat completion request respecting a shared deadline."""
        retries = 0
        t_overall_start = time.monotonic()
        last_headers: Dict[str, str] = {}

        while True:
            # Check shared end-to-end deadline
            if deadline is not None:
                remaining_s = deadline - time.monotonic()
                if remaining_s <= 0.05:
                    total_elapsed = (time.monotonic() - t_overall_start) * 1000.0
                    if on_event:
                        await on_event("request_timeout", stage, f"Deadline expired before attempt {retries}")
                    return LLMResponse(
                        text="", first_token_time_ms=None, total_time_ms=total_elapsed,
                        tokens_in=0, tokens_out=0, retries=retries,
                        status="timeout", headers=last_headers,
                    )
            else:
                remaining_s = API_TIMEOUT_S

            call_timeout = min(API_TIMEOUT_S, max(0.1, remaining_s))

            if on_event:
                await on_event("model_call_start", stage, f"attempt={retries}, timeout_s={call_timeout:.1f}")

            try:
                resp = await self._do_stream(
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    retries_so_far=retries,
                    call_timeout=call_timeout,
                    deadline=deadline,
                )
                if on_event:
                    await on_event("model_call_end", stage, f"status={resp.status}, in={resp.tokens_in}, out={resp.tokens_out}")
                return resp

            except RateLimitError as e:
                retries += 1
                last_headers = e.headers
                if on_event:
                    await on_event("retry_start", stage, f"reason=rate_limit_429, attempt={retries}, retry_after={e.retry_after}")

                # If retry-after exceeds client budget or remaining deadline, abort immediately
                if e.retry_after is not None:
                    if e.retry_after > RETRY_MAX_DELAY_S or (deadline and e.retry_after > (deadline - time.monotonic())):
                        total_elapsed = (time.monotonic() - t_overall_start) * 1000.0
                        if on_event:
                            await on_event("request_timeout", stage, f"retry_after={e.retry_after}s exceeds deadline")
                        return LLMResponse(
                            text="", first_token_time_ms=None, total_time_ms=total_elapsed,
                            tokens_in=0, tokens_out=0, retries=retries,
                            status="rate_limited", headers=last_headers,
                        )

                if retries > MAX_LLM_RETRIES:
                    total_elapsed = (time.monotonic() - t_overall_start) * 1000.0
                    return LLMResponse(
                        text="", first_token_time_ms=None, total_time_ms=total_elapsed,
                        tokens_in=0, tokens_out=0, retries=retries,
                        status="rate_limited", headers=last_headers,
                    )

                # Calculate backoff delay
                delay = min(
                    RETRY_BASE_DELAY_S * (2 ** (retries - 1)) + random.uniform(0.1, 0.5),
                    RETRY_MAX_DELAY_S,
                )
                if e.retry_after is not None:
                    delay = min(RETRY_MAX_DELAY_S, max(delay, e.retry_after))

                if deadline is not None and (time.monotonic() + delay) > deadline:
                    total_elapsed = (time.monotonic() - t_overall_start) * 1000.0
                    if on_event:
                        await on_event("request_timeout", stage, f"backoff_delay={delay:.1f}s exceeds deadline")
                    return LLMResponse(
                        text="", first_token_time_ms=None, total_time_ms=total_elapsed,
                        tokens_in=0, tokens_out=0, retries=retries,
                        status="timeout", headers=last_headers,
                    )

                if on_event:
                    await on_event("retry_backoff", stage, f"delay_s={delay:.2f}, retry_after={e.retry_after}")
                await asyncio.sleep(delay)
                if on_event:
                    await on_event("retry_end", stage, f"attempt={retries}")

            except NonRetryableError as e:
                total_elapsed = (time.monotonic() - t_overall_start) * 1000.0
                if on_event:
                    await on_event("model_call_end", stage, f"status=error, non_retryable={e}")
                return LLMResponse(
                    text="", first_token_time_ms=None, total_time_ms=total_elapsed,
                    tokens_in=0, tokens_out=0, retries=retries,
                    status="error", headers=last_headers,
                )

            except (TimeoutError, asyncio.TimeoutError, httpx.TimeoutException) as e:
                retries += 1
                if on_event:
                    await on_event("retry_start", stage, f"reason=timeout, attempt={retries}")
                if retries > MAX_LLM_RETRIES or (deadline and time.monotonic() >= deadline):
                    total_elapsed = (time.monotonic() - t_overall_start) * 1000.0
                    if on_event:
                        await on_event("request_timeout", stage, f"max_retries_reached")
                    return LLMResponse(
                        text="", first_token_time_ms=None, total_time_ms=total_elapsed,
                        tokens_in=0, tokens_out=0, retries=retries,
                        status="timeout", headers=last_headers,
                    )
                if on_event:
                    await on_event("retry_backoff", stage, f"delay_s=0.50")
                await asyncio.sleep(0.5)
                if on_event:
                    await on_event("retry_end", stage, f"attempt={retries}")

            except Exception as e:
                retries += 1
                if on_event:
                    await on_event("retry_start", stage, f"reason=exception, error={e}, attempt={retries}")
                if retries > MAX_LLM_RETRIES or (deadline and time.monotonic() >= deadline):
                    total_elapsed = (time.monotonic() - t_overall_start) * 1000.0
                    return LLMResponse(
                        text="", first_token_time_ms=None, total_time_ms=total_elapsed,
                        tokens_in=0, tokens_out=0, retries=retries,
                        status="error", headers=last_headers,
                    )
                delay = min(
                    RETRY_BASE_DELAY_S * (2 ** (retries - 1)) + random.uniform(0.1, 0.5),
                    RETRY_MAX_DELAY_S,
                )
                if on_event:
                    await on_event("retry_backoff", stage, f"delay_s={delay:.2f}")
                await asyncio.sleep(delay)
                if on_event:
                    await on_event("retry_end", stage, f"attempt={retries}")
                await asyncio.sleep(delay)

    async def _do_stream(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        retries_so_far: int,
        call_timeout: float,
        deadline: Optional[float] = None,
    ) -> LLMResponse:
        """Execute one streaming HTTP request attempt."""
        client = await self._get_client()
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        t_start = time.monotonic()
        first_token_mono: Optional[float] = None
        full_text = ""
        tokens_in = 0
        tokens_out = 0
        response_headers: Dict[str, str] = {}

        # Use httpx.Timeout configured with the remaining deadline
        request_timeout = httpx.Timeout(call_timeout, connect=min(10.0, call_timeout))

        async with client.stream("POST", url, json=payload, timeout=request_timeout) as resp:
            response_headers = {k.lower(): v for k, v in resp.headers.items()}

            if resp.status_code == 429:
                retry_after_hdr = resp.headers.get("retry-after")
                retry_val = float(retry_after_hdr) if retry_after_hdr else None
                body = await resp.aread()
                raise RateLimitError(
                    retry_after=retry_val,
                    body=body.decode(errors="replace"),
                    headers=response_headers,
                )

            # Non-retryable client errors
            if resp.status_code in (400, 401, 403, 404):
                body = await resp.aread()
                raise NonRetryableError(resp.status_code, body.decode(errors="replace")[:400])

            if resp.status_code != 200:
                body = await resp.aread()
                raise LLMError(f"HTTP {resp.status_code}: {body.decode(errors='replace')[:400]}")

            async for line in resp.aiter_lines():
                if deadline is not None and time.monotonic() >= deadline:
                    raise asyncio.TimeoutError("Pipeline deadline exceeded during streaming")

                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break

                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue

                # Strict extraction of content token (ignore metadata-only chunks)
                choices = chunk.get("choices", [])
                if choices:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        if first_token_mono is None:
                            first_token_mono = time.monotonic()
                        full_text += content

                # Extract usage metadata
                usage = chunk.get("usage") or chunk.get("x_groq", {}).get("usage")
                if usage:
                    tokens_in = usage.get("prompt_tokens", 0)
                    tokens_out = usage.get("completion_tokens", 0)

        t_end = time.monotonic()
        total_time_ms = (t_end - t_start) * 1000.0

        first_token_ms: Optional[float] = None
        if first_token_mono is not None:
            first_token_ms = (first_token_mono - t_start) * 1000.0
            if first_token_ms > total_time_ms:
                raise ValueError(
                    f"Measurement anomaly: first_token_ms ({first_token_ms:.2f}) > "
                    f"total_time_ms ({total_time_ms:.2f})"
                )

        return LLMResponse(
            text=full_text,
            first_token_time_ms=first_token_ms,
            total_time_ms=total_time_ms,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            retries=retries_so_far,
            status="ok" if full_text else "error",
            first_token_monotonic=first_token_mono,
            headers=response_headers,
        )
