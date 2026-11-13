"""Unit tests for Citation Verification and Correctness-First Policies (Part 6)."""
import asyncio
import os
import time
import unittest
from unittest.mock import AsyncMock, MagicMock

import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "relay")))

from pipeline import Pipeline, PipelineResult
from rate_limiter import TokenBucketRateLimiter
from config import RateLimiterConfig, RetrievalSetting


class TestCitationVerification(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.mock_index = MagicMock()
        self.mock_index.search.return_value = [
            MagicMock(citation_label=lambda: "[Attention Is All You Need, p.5]", text="Passage text describing 8 heads.")
        ]
        self.mock_logger = MagicMock()
        self.mock_logger.log = AsyncMock()
        self.mock_logger.log_event = AsyncMock()

    async def test_unsupported_claim_detected_and_retried(self):
        """When draft citations are unsupported, Step 4 must trigger loop back to Step 3."""
        mock_llm = MagicMock()
        # Step 1: Query analysis ok
        # Step 3 (Attempt 0): Draft with bad citation
        # Step 4 (Attempt 0): Verification rejects
        # Step 3 (Attempt 1): Draft with corrected citation
        # Step 4 (Attempt 1): Verification approves
        mock_llm.chat_stream = AsyncMock(side_effect=[
            MagicMock(status="ok", text='{"answerable": true, "keywords": ["heads"]}', tokens_in=20, tokens_out=15, retries=0, headers={}),
            MagicMock(status="ok", text="The model has 16 heads [Attention Is All You Need, p.99]", first_token_monotonic=time.monotonic(), tokens_in=50, tokens_out=30, retries=0, headers={}),
            MagicMock(status="ok", text='{"valid": false, "issues": ["Unsupported claim: page 99 does not exist."]}', tokens_in=40, tokens_out=20, retries=0, headers={}),
            MagicMock(status="ok", text="The base model uses 8 attention heads [Attention Is All You Need, p.5].", first_token_monotonic=time.monotonic(), tokens_in=50, tokens_out=30, retries=0, headers={}),
            MagicMock(status="ok", text='{"valid": true, "issues": []}', tokens_in=40, tokens_out=20, retries=0, headers={}),
        ])

        rate_limiter = TokenBucketRateLimiter(RateLimiterConfig(rpm=100, tpm=100000), state_file=None)
        pipeline = Pipeline(self.mock_index, mock_llm, rate_limiter, self.mock_logger)

        res = await pipeline.run("How many attention heads does the Transformer base model use?")
        self.assertEqual(res.status, "ok")
        self.assertTrue(res.verification_passed)
        self.assertIn("uses 8 attention heads", res.answer)
        self.assertEqual(res.answer_grade, "correct")
        self.assertGreaterEqual(res.retries, 1)

    async def test_regeneration_limits_reached_withholds_draft(self):
        """When correction retries hit MAX_CITATION_RETRIES without valid citations, draft must be withheld."""
        mock_llm = MagicMock()
        mock_llm.chat_stream = AsyncMock(side_effect=[
            # Step 1: Query Analysis
            MagicMock(status="ok", text='{"answerable": true, "keywords": ["heads"]}', tokens_in=20, tokens_out=15, retries=0, headers={}),
            # Attempt 0: Draft + Reject
            MagicMock(status="ok", text="Draft 0 with fake citation [Fake, p.1]", first_token_monotonic=time.monotonic(), tokens_in=30, tokens_out=20, retries=0, headers={}),
            MagicMock(status="ok", text='{"valid": false, "issues": ["Fake citation"]}', tokens_in=30, tokens_out=10, retries=0, headers={}),
            # Attempt 1: Draft + Reject
            MagicMock(status="ok", text="Draft 1 with fake citation [Fake, p.2]", first_token_monotonic=time.monotonic(), tokens_in=30, tokens_out=20, retries=0, headers={}),
            MagicMock(status="ok", text='{"valid": false, "issues": ["Fake citation"]}', tokens_in=30, tokens_out=10, retries=0, headers={}),
            # Attempt 2: Draft + Reject
            MagicMock(status="ok", text="Draft 2 with fake citation [Fake, p.3]", first_token_monotonic=time.monotonic(), tokens_in=30, tokens_out=20, retries=0, headers={}),
            MagicMock(status="ok", text='{"valid": false, "issues": ["Fake citation"]}', tokens_in=30, tokens_out=10, retries=0, headers={}),
        ])

        rate_limiter = TokenBucketRateLimiter(RateLimiterConfig(rpm=100, tpm=100000), state_file=None)
        pipeline = Pipeline(self.mock_index, mock_llm, rate_limiter, self.mock_logger)

        res = await pipeline.run("How many attention heads does the Transformer base model use?")
        self.assertEqual(res.status, "error")
        self.assertFalse(res.verification_passed)
        self.assertIn("Unverified answers are withheld", res.answer)
        self.assertNotIn("Draft 2 with fake citation", res.answer)

    async def test_budget_exhaustion_during_verification_withholds_draft(self):
        """When rate limiter quota exhausts at Step 4, unverified draft must NEVER be served."""
        mock_llm = MagicMock()
        mock_llm.chat_stream = AsyncMock(side_effect=[
            MagicMock(status="ok", text='{"answerable": true, "keywords": ["heads"]}', tokens_in=20, tokens_out=15, retries=0, headers={}),
            MagicMock(status="ok", text="Unverified answer [Attention Is All You Need, p.5]", first_token_monotonic=time.monotonic(), tokens_in=50, tokens_out=30, retries=0, headers={}),
        ])

        # RPD = 2 (consumed by step 1 and step 3)
        rate_limiter = TokenBucketRateLimiter(RateLimiterConfig(rpm=60, tpm=10000, rpd=2, tpd=10000), state_file=None)
        pipeline = Pipeline(self.mock_index, mock_llm, rate_limiter, self.mock_logger)

        res = await pipeline.run("How many attention heads?")
        self.assertEqual(res.status, "rate_limited")
        self.assertFalse(res.verification_passed)
        self.assertIn("mandatory citation verification could not be completed", res.answer)
        self.assertNotIn("Unverified answer", res.answer)

    async def test_verification_service_failure_withholds_draft(self):
        """When verification model call fails (e.g. 500 error), draft must be withheld."""
        mock_llm = MagicMock()
        mock_llm.chat_stream = AsyncMock(side_effect=[
            MagicMock(status="ok", text='{"answerable": true, "keywords": ["heads"]}', tokens_in=20, tokens_out=15, retries=0, headers={}),
            MagicMock(status="ok", text="Draft [Attention Is All You Need, p.5]", first_token_monotonic=time.monotonic(), tokens_in=50, tokens_out=30, retries=0, headers={}),
            MagicMock(status="error", text="", tokens_in=0, tokens_out=0, retries=1, headers={}),
        ])

        rate_limiter = TokenBucketRateLimiter(RateLimiterConfig(), state_file=None)
        pipeline = Pipeline(self.mock_index, mock_llm, rate_limiter, self.mock_logger)

        res = await pipeline.run("How many heads?")
        self.assertEqual(res.status, "error")
        self.assertFalse(res.verification_passed)
        self.assertIn("Citation verification service failed", res.answer)
        self.assertNotIn("Draft [Attention", res.answer)

    async def test_unanswerable_question_strictly_refused(self):
        """Out-of-domain questions must be refused immediately at Step 1."""
        mock_llm = MagicMock()
        mock_llm.chat_stream = AsyncMock(return_value=MagicMock(
            status="ok", text='{"answerable": false, "reasoning": "Geography out of domain"}', tokens_in=20, tokens_out=15, retries=0, headers={},
        ))

        rate_limiter = TokenBucketRateLimiter(RateLimiterConfig(), state_file=None)
        pipeline = Pipeline(self.mock_index, mock_llm, rate_limiter, self.mock_logger)

        res = await pipeline.run("What is the capital of France?")
        self.assertEqual(res.status, "ok")
        self.assertEqual(res.answer_grade, "refused_correctly")
        self.assertIn("do not contain information about this topic", res.answer)
        self.assertIsNone(res.first_token_ms)


if __name__ == "__main__":
    unittest.main()
