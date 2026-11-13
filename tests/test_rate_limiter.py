"""Unit tests for TokenBucketRateLimiter and quota management (Parts 3 & 8)."""
import asyncio
import os
import time
import tempfile
import unittest
from datetime import datetime, timezone, timedelta

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "relay")))

from rate_limiter import TokenBucketRateLimiter
from config import RateLimiterConfig


class TestRateLimiter(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.state_file = os.path.join(self.temp_dir.name, "quota_state.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    async def test_deterministic_bucket_consumption(self):
        """Test exact deduction of RPM and TPM tokens on acquisition."""
        config = RateLimiterConfig(rpm=60, tpm=6000, itpm=5000, rpd=100, tpd=100000)
        limiter = TokenBucketRateLimiter(config, state_file=self.state_file)

        self.assertEqual(limiter._rpm_tokens, 60.0)
        self.assertEqual(limiter._tpm_tokens, 6000.0)
        self.assertEqual(limiter._itpm_tokens, 5000.0)

        # Acquire 500 input + 200 output tokens
        status, wait_s = await limiter.acquire_or_shed(
            estimated_input_tokens=500,
            estimated_output_tokens=200,
            patience_s=1.0,
        )
        self.assertEqual(status, "acquired")
        self.assertEqual(wait_s, 0.0)
        self.assertEqual(limiter._rpm_tokens, 59.0)
        self.assertEqual(limiter._tpm_tokens, 5300.0)
        self.assertEqual(limiter._itpm_tokens, 4500.0)
        self.assertEqual(limiter._daily_requests, 1)
        self.assertEqual(limiter._daily_tokens, 700)

    async def test_daily_budget_completely_exhausted(self):
        """When daily budget is completely exhausted, acquire_or_shed must shed immediately."""
        config = RateLimiterConfig(rpm=60, tpm=6000, rpd=2, tpd=10000)
        limiter = TokenBucketRateLimiter(config, state_file=self.state_file)

        # Consume first 2 requests
        s1, _ = await limiter.acquire_or_shed(100, 50, patience_s=1.0)
        s2, _ = await limiter.acquire_or_shed(100, 50, patience_s=1.0)
        self.assertEqual(s1, "acquired")
        self.assertEqual(s2, "acquired")

        # 3rd request must be shed immediately without waiting
        t0 = time.monotonic()
        s3, w3 = await limiter.acquire_or_shed(100, 50, patience_s=5.0)
        elapsed = time.monotonic() - t0

        self.assertEqual(s3, "shed")
        self.assertEqual(w3, 0.0)
        self.assertLess(elapsed, 0.1)  # Instant short-circuit
        self.assertTrue(limiter.is_daily_exhausted)

    async def test_quota_persistence_across_process_restart(self):
        """Simulate process restart: new limiter instance must reload exhausted quota from disk."""
        config = RateLimiterConfig(model_id="test-model", rpm=60, tpm=6000, rpd=1, tpd=10000)
        limiter1 = TokenBucketRateLimiter(config, state_file=self.state_file)

        s1, _ = await limiter1.acquire_or_shed(100, 50)
        self.assertEqual(s1, "acquired")
        self.assertTrue(limiter1.is_daily_exhausted)

        # Process restart (new object loading same state file)
        limiter2 = TokenBucketRateLimiter(config, state_file=self.state_file)
        self.assertTrue(limiter2.is_daily_exhausted)
        s2, _ = await limiter2.acquire_or_shed(100, 50)
        self.assertEqual(s2, "shed")

    async def test_requests_arriving_after_daily_reset(self):
        """When time passes daily reset timestamp, daily counters must reset to 0."""
        config = RateLimiterConfig(rpm=60, tpm=6000, rpd=1, tpd=10000)
        limiter = TokenBucketRateLimiter(config, state_file=self.state_file)

        await limiter.acquire_or_shed(100, 50)
        self.assertTrue(limiter.is_daily_exhausted)

        # Artificially set reset timestamp in the past
        limiter._day_reset_timestamp = time.time() - 10.0

        # Next acquire should reset daily counters and acquire
        s, _ = await limiter.acquire_or_shed(100, 50)
        self.assertEqual(s, "acquired")
        self.assertEqual(limiter._daily_requests, 1)

    async def test_update_from_provider_headers(self):
        """Test calibrating reset timestamps from provider HTTP headers."""
        limiter = TokenBucketRateLimiter(RateLimiterConfig(), state_file=self.state_file)

        headers = {
            "retry-after": "12.5",
            "x-ratelimit-reset-tokens": "2.4s",
            "x-ratelimit-reset-requests": "3600s",
        }
        limiter.update_from_headers(headers)

        self.assertEqual(limiter.last_retry_after, 12.5)
        self.assertEqual(limiter.last_reset_tokens_s, 2.4)
        self.assertEqual(limiter.last_reset_requests_s, 3600.0)

    async def test_reservation_release_on_cancellation(self):
        """When an acquired reservation is released, tokens and daily counters must be restored."""
        config = RateLimiterConfig(rpm=60, tpm=6000, rpd=10, tpd=10000)
        limiter = TokenBucketRateLimiter(config, state_file=self.state_file)

        await limiter.acquire(500, 200)
        self.assertEqual(limiter._daily_requests, 1)
        self.assertEqual(limiter._daily_tokens, 700)

        limiter.release_reservation(500, 200)
        self.assertEqual(limiter._daily_requests, 0)
        self.assertEqual(limiter._daily_tokens, 0)
        self.assertEqual(limiter._rpm_tokens, 60.0)
        self.assertEqual(limiter._tpm_tokens, 6000.0)


if __name__ == "__main__":
    unittest.main()
