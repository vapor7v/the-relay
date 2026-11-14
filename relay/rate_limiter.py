"""Multi-dimensional token-bucket rate limiter with async admission queue.

Proactively limits requests before hitting external APIs to eliminate wasted round-trips.
Tracks:
- Requests Per Minute (RPM)
- Total Tokens Per Minute (TPM)
- Input Tokens Per Minute (ITPM)
- Requests Per Day (RPD)
- Tokens Per Day (TPD)
- Continuous leaky-bucket replenishment via monotonic clock
- UTC midnight and provider-header daily resets
- Cancellation-safe admission queue with persistent quota support
"""
import asyncio
import os
import json
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any

from config import RateLimiterConfig, QUOTA_STATE_JSON


import re


def parse_duration_str(val: str) -> Optional[float]:
    """Parse duration strings like '1m26.4s', '2.31s', '45s', '1h30m' into seconds."""
    if not val:
        return None
    val = val.strip().lower()
    matches = re.findall(r'(\d+(?:\.\d+)?)([hms])', val)
    if matches:
        tot = 0.0
        for num, unit in matches:
            n = float(num)
            if unit == 'h':
                tot += n * 3600.0
            elif unit == 'm':
                tot += n * 60.0
            elif unit == 's':
                tot += n
        return tot
    try:
        return float(val.rstrip('s'))
    except ValueError:
        return None


class TokenBucketRateLimiter:
    """Dual token-bucket (RPM + TPM/ITPM) with daily counters and async queue."""

    def __init__(self, config: Optional[RateLimiterConfig] = None, state_file: Optional[str] = QUOTA_STATE_JSON):
        self.config = config or RateLimiterConfig()
        self.state_file = state_file

        # Per-minute buckets (refill continuously)
        self._rpm_tokens = float(self.config.rpm)
        self._tpm_tokens = float(self.config.tpm)
        self._itpm_tokens = float(self.config.itpm if self.config.itpm is not None else self.config.tpm)
        self._last_refill = time.monotonic()

        # Queue tracking
        self._queue_length = 0
        self._peak_queue = 0

        # Mutex for thread-safe state access
        self._lock = asyncio.Lock()

        # Daily tracking
        self._daily_requests = 0
        self._daily_tokens = 0
        self._day_reset_timestamp = self._calc_next_utc_midnight()
        self._load_quota_state()

        # Provider observed telemetry
        self.last_retry_after: Optional[float] = None
        self.last_reset_tokens_s: Optional[float] = None
        self.last_reset_requests_s: Optional[float] = None

    def _calc_next_utc_midnight(self) -> float:
        """Calculate unix epoch timestamp for upcoming 00:00:00 UTC."""
        now_utc = datetime.now(timezone.utc)
        tomorrow_utc = (now_utc + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        return tomorrow_utc.timestamp()

    def _load_quota_state(self):
        """Restore daily quota counters from disk if persistent file exists and is from the same UTC day."""
        if not self.state_file or not os.path.exists(self.state_file):
            return
        try:
            with open(self.state_file, "r") as f:
                data = json.load(f)
            saved_date = data.get("date_utc")
            current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if saved_date == current_date and data.get("model_id") == self.config.model_id:
                self._daily_requests = int(data.get("daily_requests", 0))
                self._daily_tokens = int(data.get("daily_tokens", 0))
                self._day_reset_timestamp = float(data.get("day_reset_timestamp", self._day_reset_timestamp))
        except Exception:
            pass

    def _save_quota_state(self):
        """Persist current daily quota state to prevent silent quota resets on process restart."""
        if not self.state_file:
            return
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            current_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            data = {
                "date_utc": current_date,
                "model_id": self.config.model_id,
                "daily_requests": self._daily_requests,
                "daily_tokens": self._daily_tokens,
                "day_reset_timestamp": self._day_reset_timestamp,
                "updated_at": time.time(),
            }
            with open(self.state_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def _check_daily_reset(self):
        """Reset daily counters if past the daily reset timestamp."""
        now_epoch = time.time()
        if now_epoch >= self._day_reset_timestamp:
            self._daily_requests = 0
            self._daily_tokens = 0
            self._day_reset_timestamp = self._calc_next_utc_midnight()
            self._save_quota_state()

    def _refill(self):
        """Refill per-minute buckets based on elapsed monotonic time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._last_refill = now

        # Continuous replenishment rate = capacity / 60 seconds
        rpm_rate = self.config.rpm / 60.0
        tpm_rate = self.config.tpm / 60.0
        itpm_rate = (self.config.itpm / 60.0) if self.config.itpm else tpm_rate

        self._rpm_tokens = min(float(self.config.rpm), self._rpm_tokens + elapsed * rpm_rate)
        self._tpm_tokens = min(float(self.config.tpm), self._tpm_tokens + elapsed * tpm_rate)
        self._itpm_tokens = min(
            float(self.config.itpm if self.config.itpm else self.config.tpm),
            self._itpm_tokens + elapsed * itpm_rate
        )

    @property
    def daily_budget_remaining(self) -> Tuple[int, int]:
        """Return (requests_remaining, tokens_remaining) for the day."""
        self._check_daily_reset()
        rem_req = max(0, self.config.rpd - self._daily_requests)
        rem_tok = max(0, self.config.tpd - self._daily_tokens)
        return rem_req, rem_tok

    @property
    def is_daily_exhausted(self) -> bool:
        rem_req, rem_tok = self.daily_budget_remaining
        return rem_req <= 0 or rem_tok <= 0

    @property
    def peak_queue_length(self) -> int:
        return self._peak_queue

    @property
    def current_queue_length(self) -> int:
        return self._queue_length

    def update_from_headers(self, headers: Dict[str, Any]):
        """Calibrate limits from live HTTP response headers."""
        # Check retry-after
        ra = headers.get("retry-after")
        if ra is not None:
            try:
                self.last_retry_after = float(ra)
            except ValueError:
                pass

        # Check reset tokens
        rst_tok = headers.get("x-ratelimit-reset-tokens")
        if rst_tok:
            parsed_tok = parse_duration_str(str(rst_tok))
            if parsed_tok is not None:
                self.last_reset_tokens_s = parsed_tok

        # Check reset requests (daily)
        rst_req = headers.get("x-ratelimit-reset-requests")
        if rst_req:
            parsed_req = parse_duration_str(str(rst_req))
            if parsed_req is not None:
                self._day_reset_timestamp = time.time() + parsed_req
                self.last_reset_requests_s = parsed_req

        # Check remaining requests / tokens
        rem_req = headers.get("x-ratelimit-remaining-requests")
        if rem_req is not None:
            try:
                rem_val = int(rem_req)
                self.last_remaining_requests = rem_val
                calibrated_used = max(0, self.config.rpd - rem_val)
                self._daily_requests = max(self._daily_requests, calibrated_used)
            except (ValueError, TypeError):
                pass

        rem_tok = headers.get("x-ratelimit-remaining-tokens")
        if rem_tok is not None:
            try:
                self.last_remaining_tokens = int(rem_tok)
            except (ValueError, TypeError):
                pass

        lim_req = headers.get("x-ratelimit-limit-requests")
        if lim_req is not None:
            try:
                self.last_limit_requests = int(lim_req)
            except (ValueError, TypeError):
                pass

        lim_tok = headers.get("x-ratelimit-limit-tokens")
        if lim_tok is not None:
            try:
                self.last_limit_tokens = int(lim_tok)
            except (ValueError, TypeError):
                pass

    async def acquire(
        self,
        estimated_input_tokens: int = 500,
        estimated_output_tokens: int = 300,
        deadline: Optional[float] = None,
    ) -> Optional[float]:
        """Wait until capacity is available. Returns wait time in seconds, or None if budget exhausted.
        
        The lock is strictly held only while inspecting and updating bucket state.
        Tasks sleep OUTSIDE the lock.
        """
        self._check_daily_reset()

        total_tokens = estimated_input_tokens + estimated_output_tokens

        # Check daily limits first
        if self._daily_requests >= self.config.rpd or (self._daily_tokens + total_tokens) > self.config.tpd:
            return None  # Daily quota exhausted

        t_start = time.monotonic()
        total_wait = 0.0

        while True:
            # Check deadline before waiting
            if deadline is not None and time.monotonic() >= deadline:
                raise asyncio.TimeoutError("Deadline expired while waiting for rate limiter capacity")

            wait = 0.0
            async with self._lock:
                self._check_daily_reset()
                if self._daily_requests >= self.config.rpd or (self._daily_tokens + total_tokens) > self.config.tpd:
                    return None

                self._refill()

                has_rpm = self._rpm_tokens >= 1.0
                has_tpm = self._tpm_tokens >= total_tokens
                has_itpm = (self._itpm_tokens >= estimated_input_tokens) if self.config.itpm else True

                if has_rpm and has_tpm and has_itpm:
                    # Capacity available: deduct and admit
                    self._rpm_tokens -= 1.0
                    self._tpm_tokens -= total_tokens
                    if self.config.itpm:
                        self._itpm_tokens -= estimated_input_tokens

                    self._daily_requests += 1
                    self._daily_tokens += total_tokens
                    self._save_quota_state()
                    return total_wait

                # Calculate shortest wait until buckets refill
                rpm_rate = (self.config.rpm / 60.0) if self.config.rpm > 0 else 0.0
                tpm_rate = (self.config.tpm / 60.0) if self.config.tpm > 0 else 0.0
                itpm_rate = (self.config.itpm / 60.0) if (self.config.itpm and self.config.itpm > 0) else tpm_rate

                rpm_wait = (1.0 - self._rpm_tokens) / rpm_rate if (not has_rpm and rpm_rate > 0) else (1.0 if not has_rpm else 0.0)
                tpm_wait = (total_tokens - self._tpm_tokens) / tpm_rate if (not has_tpm and tpm_rate > 0) else (1.0 if not has_tpm else 0.0)
                itpm_wait = 0.0
                if self.config.itpm and not has_itpm:
                    itpm_wait = (estimated_input_tokens - self._itpm_tokens) / itpm_rate if itpm_rate > 0 else 1.0

                wait = max(rpm_wait, tpm_wait, itpm_wait, 0.02)
                wait = min(wait, 1.0)  # Sleep in slices to allow continuous checking

            # Sleep strictly outside the lock
            await asyncio.sleep(wait)
            total_wait += wait

    def release_reservation(self, estimated_input_tokens: int = 500, estimated_output_tokens: int = 300):
        """Release reserved tokens back to buckets on cancellation or early abort."""
        total_tokens = estimated_input_tokens + estimated_output_tokens
        self._rpm_tokens = min(float(self.config.rpm), self._rpm_tokens + 1.0)
        self._tpm_tokens = min(float(self.config.tpm), self._tpm_tokens + total_tokens)
        if self.config.itpm:
            self._itpm_tokens = min(float(self.config.itpm), self._itpm_tokens + estimated_input_tokens)
        self._daily_requests = max(0, self._daily_requests - 1)
        self._daily_tokens = max(0, self._daily_tokens - total_tokens)
        self._save_quota_state()

    def report_actual_tokens(
        self,
        estimated_total: int,
        actual_in: int,
        actual_out: int,
    ):
        """Adjust token budget after knowing actual API consumption."""
        actual_total = actual_in + actual_out
        diff = estimated_total - actual_total
        if diff != 0:
            self._tpm_tokens = min(float(self.config.tpm), self._tpm_tokens + diff)
            self._daily_tokens = max(0, self._daily_tokens - diff)
            self._save_quota_state()

    async def acquire_or_shed(
        self,
        estimated_input_tokens: int = 500,
        estimated_output_tokens: int = 300,
        patience_s: float = 15.0,
        deadline: Optional[float] = None,
    ) -> Tuple[str, float]:
        """Try to acquire within patience window and deadline.
        
        Returns (status, wait_seconds).
        status: "acquired", "shed" (queue full/daily quota exhausted), "timeout" (waited too long).
        """
        async with self._lock:
            self._queue_length += 1
            if self._queue_length > self._peak_queue:
                self._peak_queue = self._queue_length

            # Check queue capacity immediately
            if self._queue_length > self.config.max_queue:
                self._queue_length -= 1
                return "shed", 0.0

            # Pre-check daily quota
            self._check_daily_reset()
            total_est = estimated_input_tokens + estimated_output_tokens
            if self._daily_requests >= self.config.rpd or (self._daily_tokens + total_est) > self.config.tpd:
                self._queue_length -= 1
                return "shed", 0.0

        effective_timeout = patience_s
        if deadline is not None:
            remaining_s = max(0.001, deadline - time.monotonic())
            effective_timeout = min(effective_timeout, remaining_s)

        try:
            result = await asyncio.wait_for(
                self.acquire(
                    estimated_input_tokens=estimated_input_tokens,
                    estimated_output_tokens=estimated_output_tokens,
                    deadline=deadline,
                ),
                timeout=effective_timeout,
            )
            if result is None:
                return "shed", 0.0  # Daily quota exhausted
            return "acquired", result

        except asyncio.TimeoutError:
            return "timeout", effective_timeout
        except asyncio.CancelledError:
            # Propagate cancellation cleanly
            raise
        finally:
            async with self._lock:
                self._queue_length = max(0, self._queue_length - 1)
