# biomedical-data/bio-data/scripts/_common.py
"""Shared HTTP infra for bio-data MCP tools: rate limiting, retry, cache.

Mirrors the *role* of Claude Science's mcp_servers_common (rate limit / retry /
UA / contact-email / cache) without copying any of its code. Values learned
from external/science-skills are cited in references/bio-tools-architecture.md.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

import httpx


class RateLimiter:
    """Token-bucket-ish limiter: at most `rate` calls per second, evenly spaced."""

    def __init__(self, rate: float):
        self._min_interval = (1.0 / rate) if rate > 0 else 0.0
        self._last = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last)
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._last = now


class Retry:
    """Retry on 429 / 5xx / transport errors with exponential backoff.

    Capped so a single call cannot hang past the MCP transport budget
    (bio-tools measured ~60s; adopt the same ceiling).
    """

    def __init__(self, *, max_attempts: int = 4, budget_s: float = 55.0, base: float = 0.5):
        self._max = max_attempts
        self._budget = budget_s
        self._base = base

    def call(self, fn):
        deadline = time.monotonic() + self._budget
        last = None
        for attempt in range(self._max):
            try:
                r = fn()
                if r.status_code == 429 or 500 <= r.status_code < 600:
                    last = r
                else:
                    return r
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last = e
            if attempt + 1 == self._max or time.monotonic() >= deadline:
                break
            time.sleep(self._base * (2 ** attempt))
        if isinstance(last, Exception):
            raise last
        return last
