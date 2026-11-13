"""Automated tests for verification policy, rate limiter, and simulator calibration."""
import asyncio
import unittest
import math
import random
import time
from unittest.mock import AsyncMock, MagicMock

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from rate_limiter import TokenBucketRateLimiter, RateLimiterConfig
from simulator import SimulatorState, load_calibration
from pipeline import Pipeline, PipelineResult
from config import RetrievalSetting, PIPELINE_TIMEOUT_S


class TestVerificationPolicy(unittest.IsolatedAsyncioTestCase):
    """Automated tests for mandatory citation verification (Audit item 4)."""

    async def test_verification_refusal_when_daily_budget_exhausted_at_step_4(self):
        """When budget allows drafting but is insufficient for verification, draft must NOT be returned unverified."""
        index = MagicMock()
        index.search.return_value = [MagicMock(citation_label=lambda: "[Attention, p.1]", text="Sample passage")]

        llm = MagicMock()
        # Step 1: Query analysis ok
        # Step 3: Draft answer generated
        llm.chat_stream = AsyncMock(side_effect=[
            MagicMock(status="ok", text='{"answerable": true, "keywords": ["heads"]}', tokens_in=20, tokens_out=15, retries=0),
            MagicMock(status="ok", text="The base model has 8 heads [Attention, p.1]", first_token_monotonic=time.monotonic(), tokens_in=50, tokens_out=30, retries=0),
        ])

        # Rate limiter configured with exactly 2 requests budget (Step 1 and Step 3 consume it)
        # So by Step 4, remaining requests = 0!
        rl_config = RateLimiterConfig(rpm=60, tpm=10000, rpd=2, tpd=10000)
        rate_limiter = TokenBucketRateLimiter(rl_config)

        logger = MagicMock()
        logger.log = AsyncMock()

        pipeline = Pipeline(index, llm, rate_limiter, logger)
        result = await pipeline.run("How many heads?")

        # Hard assertion: unverified draft must NEVER be served
        self.assertIn("mandatory citation verification could not be completed", result.answer)
        self.assertNotIn("The base model has 8 heads", result.answer)
        self.assertEqual(result.status, "rate_limited")

    async def test_verification_refusal_when_verification_service_fails(self):
        """When verification model call fails, draft must NOT be returned unverified."""
        index = MagicMock()
        index.search.return_value = [MagicMock(citation_label=lambda: "[Attention, p.1]", text="Sample passage")]

        llm = MagicMock()
        llm.chat_stream = AsyncMock(side_effect=[
            # Step 1: Analysis ok
            MagicMock(status="ok", text='{"answerable": true, "keywords": ["heads"]}', tokens_in=20, tokens_out=15, retries=0),
            # Step 3: Draft ok
            MagicMock(status="ok", text="Draft answer with [Attention, p.1]", first_token_monotonic=time.monotonic(), tokens_in=50, tokens_out=30, retries=0),
            # Step 4: Verification call returns error (e.g. 500)
            MagicMock(status="error", text="", tokens_in=0, tokens_out=0, retries=1),
        ])

        rate_limiter = TokenBucketRateLimiter(RateLimiterConfig(rpm=60, tpm=10000))
        logger = MagicMock()
        logger.log = AsyncMock()

        pipeline = Pipeline(index, llm, rate_limiter, logger)
        result = await pipeline.run("How many heads?")

        self.assertIn("Citation verification service failed", result.answer)
        self.assertNotIn("Draft answer with", result.answer)
        self.assertEqual(result.status, "error")

    async def test_unanswerable_question_strictly_refused(self):
        """Unanswerable questions must be refused immediately at Step 1."""
        index = MagicMock()
        llm = MagicMock()
        llm.chat_stream = AsyncMock(return_value=MagicMock(
            status="ok", text='{"answerable": false, "reasoning": "Out of domain"}', tokens_in=20, tokens_out=15, retries=0
        ))

        rate_limiter = TokenBucketRateLimiter(RateLimiterConfig(rpm=60, tpm=10000))
        logger = MagicMock()
        logger.log = AsyncMock()

        pipeline = Pipeline(index, llm, rate_limiter, logger)
        result = await pipeline.run("What is the capital of France?")

        self.assertEqual(result.answer_grade, "refused_correctly")
        self.assertIn("do not contain information about this topic", result.answer)


class TestSimulatorCalibration(unittest.TestCase):
    """Deterministic tests for simulator calibration and bounds (Audit item 7)."""

    def test_lognormal_p95_reproduction(self):
        """Test that lognormal with mu=ln(284) and sigma=0.9731 accurately reproduces p95 ~ 1407.5ms."""
        median = 284.0
        sigma = 0.9731
        mu = math.log(median)

        # Theoretical 95th percentile
        z95 = 1.6448536
        theoretical_p95 = math.exp(mu + z95 * sigma)
        self.assertAlmostEqual(theoretical_p95, 1407.5, delta=1.0)

        # Empirical sample test with fixed seed
        random.seed(42)
        samples = [random.lognormvariate(mu, sigma) for _ in range(50000)]
        samples.sort()
        empirical_p50 = samples[len(samples) // 2]
        empirical_p95 = samples[int(len(samples) * 0.95)]

        self.assertAlmostEqual(empirical_p50, median, delta=5.0)
        self.assertAlmostEqual(empirical_p95, 1407.5, delta=30.0)

    def test_tps_bounds_never_negative_or_zero(self):
        """Ensure token generation rate is strictly positive even under extreme concurrency."""
        cal = load_calibration()
        state = SimulatorState(cal)

        # Simulate 100 concurrent requests
        state.concurrent = 100
        for _ in range(100):
            tps = state.sample_tps()
            self.assertGreater(tps, 0.0)
            self.assertGreaterEqual(tps, 15.0)  # Clamped minimum threshold

    def test_ttft_monotonic_and_load_slowdown(self):
        """Ensure load extra increases TTFT deterministically under load."""
        cal = load_calibration()
        state = SimulatorState(cal)

        random.seed(123)
        state.concurrent = 0
        ttft_idle = state.sample_ttft()

        random.seed(123)
        state.concurrent = 10
        ttft_loaded = state.sample_ttft()

        # Under same random seed, loaded TTFT must exceed idle TTFT by exactly 10 * load_slowdown_factor
        expected_diff = 10 * cal["load_slowdown_factor"]
        self.assertAlmostEqual(ttft_loaded - ttft_idle, expected_diff, places=4)


if __name__ == "__main__":
    unittest.main()
