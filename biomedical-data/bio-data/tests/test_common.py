# biomedical-data/bio-data/tests/test_common.py
import httpx

from _common import RateLimiter, Retry


def _resp(status):
    return httpx.Response(status_code=status, text="", request=httpx.Request("GET", "https://x/"))


def test_rate_limiter_paces_calls(monkeypatch):
    calls = []
    def fake_sleep(s):
        calls.append(s)
    monkeypatch.setattr("time.sleep", fake_sleep)
    limiter = RateLimiter(rate=10.0)  # 10/s => 0.1s between calls
    limiter.acquire()  # first call: no wait
    limiter.acquire()  # second call: should sleep ~0.1s
    assert calls and abs(calls[0] - 0.1) < 0.01


def test_retry_retries_on_429_then_succeeds(monkeypatch):
    sleeps = []
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        return _resp(200) if calls["n"] == 2 else _resp(429)
    r = Retry(max_attempts=4, base=0.0).call(fn)
    assert r.status_code == 200
    assert calls["n"] == 2
    assert len(sleeps) == 1


def test_retry_gives_up_after_max(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}
    def fn():
        calls["n"] += 1
        return _resp(500)
    r = Retry(max_attempts=3, base=0.0).call(fn)
    assert r.status_code == 500
    assert calls["n"] == 3
