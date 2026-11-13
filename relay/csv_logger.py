"""Telemetry and CSV logger for The Relay pipeline.

Manages two distinct telemetry files:
1. results.csv: Strictly preserves the required 12-column schema required by the assignment brief:
   request_id,scenario,source,start_time,first_token_ms,total_ms,status,retries,tokens_in,tokens_out,retrieval_setting,answer_grade
2. experiments/logs/request_events.csv: Comprehensive companion event stream logging:
   request arrival, queue entry/exit, stage start/end, model calls, draft tokens,
   verified tokens, retries, backoff delays, completion, queue depth, and active concurrency.
"""
import asyncio
import csv
import os
import time
from typing import Optional, Dict, Any

from config import RESULTS_CSV, CSV_COLUMNS, REQUEST_EVENTS_CSV

EVENT_COLUMNS = [
    "timestamp",
    "request_id",
    "scenario",
    "source",
    "event_type",
    "stage",
    "details",
    "queue_length",
    "draft_ttft_ms",
    "user_visible_ttft_ms",
    "total_ms",
]


class CSVLogger:
    """Thread-safe CSV logger for results.csv and companion request_events.csv."""

    def __init__(self, path: str = RESULTS_CSV, events_path: str = REQUEST_EVENTS_CSV):
        self.path = path
        self.events_path = events_path
        self._lock = asyncio.Lock()
        self._ensure_headers()

    def _ensure_headers(self):
        """Write headers if files do not exist or are empty."""
        # 1. results.csv
        if not os.path.exists(self.path) or os.path.getsize(self.path) == 0:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(CSV_COLUMNS)

        # 2. request_events.csv
        if self.events_path:
            if not os.path.exists(self.events_path) or os.path.getsize(self.events_path) == 0:
                os.makedirs(os.path.dirname(self.events_path) or ".", exist_ok=True)
                with open(self.events_path, "w", newline="") as f:
                    writer = csv.writer(f)
                    writer.writerow(EVENT_COLUMNS)

    async def log_event(
        self,
        request_id: str,
        scenario: str,
        source: str,
        event_type: str,
        stage: str = "",
        details: str = "",
        queue_length: int = 0,
        draft_ttft_ms: Optional[float] = None,
        user_visible_ttft_ms: Optional[float] = None,
        total_ms: Optional[float] = None,
    ):
        """Log a granular telemetry event to the companion event stream."""
        if not self.events_path:
            return

        now_str = f"{time.time():.4f}"
        d_ttft = f"{draft_ttft_ms:.1f}" if draft_ttft_ms is not None else ""
        uv_ttft = f"{user_visible_ttft_ms:.1f}" if user_visible_ttft_ms is not None else ""
        tot = f"{total_ms:.1f}" if total_ms is not None else ""

        async with self._lock:
            with open(self.events_path, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    now_str,
                    request_id,
                    scenario,
                    source,
                    event_type,
                    stage,
                    details,
                    queue_length,
                    d_ttft,
                    uv_ttft,
                    tot,
                ])

    async def log(
        self,
        request_id: str,
        scenario: str,
        source: str,
        start_time: float,
        first_token_ms: Optional[float],
        total_ms: float,
        status: str,
        retries: int,
        tokens_in: int,
        tokens_out: int,
        retrieval_setting: str,
        answer_grade: str,
    ):
        """Append one row to results.csv strictly matching the 12-column schema."""
        ft_str = f"{first_token_ms:.1f}" if (first_token_ms is not None and first_token_ms > 0) else "null"
        tot_str = f"{total_ms:.1f}"

        async with self._lock:
            with open(self.path, "a", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([
                    request_id,
                    scenario,
                    source,
                    f"{start_time:.3f}",
                    ft_str,
                    tot_str,
                    status,
                    retries,
                    tokens_in,
                    tokens_out,
                    retrieval_setting,
                    answer_grade,
                ])
