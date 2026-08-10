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
