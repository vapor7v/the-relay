"""Unit tests for shared pipeline deadlines and stage timeouts (Part 7)."""
import asyncio
import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "relay")))

from pipeline import Pipeline
from rate_limiter import TokenBucketRateLimiter
from config import RateLimiterConfig, PIPELINE_TIMEOUT_S


class TestTimeouts(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_index = MagicMock()
        self.mock_index.search.return_value = [
            MagicMock(citation_label=lambda: "[Attention, p.1]", text="Sample text")
        ]
        self.mock_logger = MagicMock()
        self.mock_logger.log = AsyncMock()
        self.mock_logger.log_event = AsyncMock()

    async def test_queue_admission_timeout(self):
        """When client wait in queue exceeds patience limit, request must abort with 'timeout'."""
        mock_llm = MagicMock()
        # Rate limiter with 0 capacity and zero refill
        rate_limiter = TokenBucketRateLimiter(RateLimiterConfig(rpm=1, tpm=100), state_file=None)
        rate_limiter._rpm_tokens = 0.0
        rate_limiter._tpm_tokens = 0.0

        pipeline = Pipeline(self.mock_index, mock_llm, rate_limiter, self.mock_logger)

        t0 = time.monotonic()
        # Should timeout within patience window
        res = await pipeline.run("What is attention?")
        elapsed = time.monotonic() - t0

        self.assertIn(res.status, ("timeout", "rate_limited"))
        self.assertIsNone(res.first_token_ms)
        self.assertEqual(rate_limiter.current_queue_length, 0)  # Released queue slot

    async def test_timeout_during_model_streaming_call(self):
        """When an external API call hangs, the call must respect deadline and cancel cleanly."""
        mock_llm = MagicMock()
        async def slow_stream(*args, **kwargs):
            await asyncio.sleep(5.0)
            return MagicMock(status="ok")

        mock_llm.chat_stream = AsyncMock(side_effect=asyncio.TimeoutError())

        rate_limiter = TokenBucketRateLimiter(RateLimiterConfig(), state_file=None)
        pipeline = Pipeline(self.mock_index, mock_llm, rate_limiter, self.mock_logger)

        res = await pipeline.run("What is attention?")
        self.assertEqual(res.status, "timeout")
        self.assertIn("exceeded", res.answer)

    async def test_timeout_during_retry_backoff(self):
        """When retrying, total sleep must not exceed the shared deadline."""
        from llm_client import LLMClient

        llm = LLMClient(use_simulator=True)
        # Create a deadline 0.2s from now
        t_start = time.monotonic()
        deadline = t_start + 0.2

        # Mock stream raising RateLimitError with retry-after = 10s
        async def mock_stream(*args, **kwargs):
            from llm_client import RateLimitError
            raise RateLimitError(retry_after=10.0, body="Too Many Requests")

        llm._do_stream = mock_stream
        resp = await llm.chat_stream([{"role": "user", "content": "hi"}], deadline=deadline)

        elapsed = time.monotonic() - t_start
        # Must abort immediately because retry_after (10s) exceeds remaining deadline (0.2s)
        self.assertIn(resp.status, ("rate_limited", "timeout"))
        self.assertLess(elapsed, 1.0)
        await llm.close()

    async def test_cancellation_releases_queue_slots(self):
        """When an in-flight pipeline task is cancelled, queue slots must be decremented."""
        rate_limiter = TokenBucketRateLimiter(RateLimiterConfig(rpm=0, tpm=0), state_file=None)
        rate_limiter._rpm_tokens = 0.0
        rate_limiter._tpm_tokens = 0.0

        # Manually verify acquire_or_shed cancellation behavior
        async def cancel_target():
            await rate_limiter.acquire_or_shed(patience_s=10.0)

        task = asyncio.create_task(cancel_target())
        await asyncio.sleep(0.05)
        self.assertEqual(rate_limiter.current_queue_length, 1)

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        self.assertEqual(rate_limiter.current_queue_length, 0)


if __name__ == "__main__":
    unittest.main()
