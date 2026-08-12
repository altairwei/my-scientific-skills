# bioinformatics/locus-novelty/scripts/_common.py
"""Shared HTTP infra for locus-novelty: rate limiting, retry, cache.

Clean-room (mirrors bio-data's _common patterns, not imported). Per-API rate
limit + 429/5xx retry + on-disk JSON cache under CLAUDE_PLUGIN_DATA."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Optional

import httpx


class RateLimiter:
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
    def __init__(self, *, max_attempts: int = 4, budget_s: float = 55.0, base: float = 0.5):
        self._max = max_attempts; self._budget = budget_s; self._base = base

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


class HttpClient:
    def __init__(self, base_url, *, ua="locus-novelty/0.1", contact_email=None,
                 rate=3.0, api_key=None, transport=None, timeout=30.0,
                 cache_dir=None, cache_ttl=300, headers=None):
        headers = dict(headers or {})
        headers.setdefault("User-Agent", ua)
        if contact_email:
            headers["Contact-Email"] = contact_email
        self._client = httpx.Client(base_url=base_url, timeout=timeout,
                                    transport=transport, headers=headers)
        self._limiter = RateLimiter(rate)
        self._retry = Retry()
        self._api_key = api_key
        self._cache_dir = Path(cache_dir) if cache_dir else None
        self._cache_ttl = cache_ttl

    def _ckey(self, path, params):
        raw = f"{path}?{sorted((params or {}).items())}"
        return hashlib.md5(raw.encode()).hexdigest()

    def _cread(self, key):
        if not self._cache_dir: return None
        p = self._cache_dir / f"{key}.json"
        if not p.exists(): return None
        if time.time() - p.stat().st_mtime > self._cache_ttl: return None
        return json.loads(p.read_text())

    def _cwrite(self, key, data):
        if not self._cache_dir: return
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        (self._cache_dir / f"{key}.json").write_text(json.dumps(data, default=str))

    def get(self, path, params=None):
        p = dict(params or {})
        if self._api_key:
            p.setdefault("api_key", self._api_key)
        key = self._ckey(path, p)
        cached = self._cread(key)
        if cached is not None:
            return cached
        self._limiter.acquire()
        r = self._retry.call(lambda: self._client.get(path, params=p))
        r.raise_for_status()
        data = r.json()
        self._cwrite(key, data)
        return data


def cache_dir() -> Optional[str]:
    d = os.environ.get("CLAUDE_PLUGIN_DATA")
    return f"{d}/cache" if d else None
