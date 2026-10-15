"""
Phase 4 Sliding-Window Rate Limiter.
Enforces Requests-Per-Minute (RPM) and Tokens-Per-Minute (TPM) limits for Groq Free Tier.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from threading import Lock
from typing import Deque, Tuple

from phase4 import config

logger = logging.getLogger(__name__)


class RateLimiter:
    """
    Thread-safe sliding-window rate limiter enforcing RPM and TPM.
    Maintains timestamped queues of requests and tokens within a 60-second window.
    """

    def __init__(
        self,
        max_rpm: int = config.RATE_LIMIT_RPM,
        max_tpm: int = config.RATE_LIMIT_TPM,
        window_sec: float = 60.0,
    ) -> None:
        self.max_rpm = max_rpm
        self.max_tpm = max_tpm
        self.window_sec = window_sec

        self._request_times: Deque[float] = deque()
        self._token_log: Deque[Tuple[float, int]] = deque()
        self._lock = Lock()

    def _purge_expired(self, now: float) -> None:
        threshold = now - self.window_sec
        while self._request_times and self._request_times[0] <= threshold:
            self._request_times.popleft()
        while self._token_log and self._token_log[0][0] <= threshold:
            self._token_log.popleft()

    def current_usage(self) -> Tuple[int, int]:
        """Returns (current_rpm, current_tpm) within current active window."""
        with self._lock:
            now = time.time()
            self._purge_expired(now)
            rpm = len(self._request_times)
            tpm = sum(tokens for _, tokens in self._token_log)
            return rpm, tpm

    def acquire(self, estimated_tokens: int = 1500) -> float:
        """
        Wait until capacity is available under both RPM and TPM caps.
        Returns total time waited in seconds.
        """
        total_waited = 0.0

        while True:
            with self._lock:
                now = time.time()
                self._purge_expired(now)

                current_rpm = len(self._request_times)
                current_tpm = sum(tokens for _, tokens in self._token_log)

                # Check if adding this request would breach limits
                if (current_rpm < self.max_rpm) and ((current_tpm + estimated_tokens) <= self.max_tpm):
                    # Reserve slot
                    self._request_times.append(now)
                    self._token_log.append((now, estimated_tokens))
                    return total_waited

                # Calculate required sleep duration to release oldest slot
                sleep_sec = 0.5
                if self._request_times:
                    oldest_req = self._request_times[0]
                    sleep_sec = max(sleep_sec, (oldest_req + self.window_sec) - now + 0.1)
                if self._token_log:
                    oldest_tok = self._token_log[0][0]
                    sleep_sec = max(sleep_sec, (oldest_tok + self.window_sec) - now + 0.1)

            logger.info(
                "Rate limiter active: current RPM=%d/%d, TPM=%d/%d. Sleeping for %.2fs...",
                current_rpm, self.max_rpm, current_tpm, self.max_tpm, sleep_sec
            )
            time.sleep(sleep_sec)
            total_waited += sleep_sec

    def update_actual_usage(self, estimated_tokens: int, actual_tokens: int) -> None:
        """Adjust token log after completion with actual token count from API response."""
        with self._lock:
            now = time.time()
            self._purge_expired(now)
            # Find and update recent matching reservation
            diff = actual_tokens - estimated_tokens
            if diff != 0 and self._token_log:
                # Add difference to the most recent entry
                last_time, last_tokens = self._token_log[-1]
                self._token_log[-1] = (last_time, max(0, last_tokens + diff))
