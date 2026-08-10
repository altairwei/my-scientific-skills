# biomedical-data/bio-data/tests/test_common.py
from _common import RateLimiter


def test_rate_limiter_paces_calls(monkeypatch):
    calls = []
    def fake_sleep(s):
        calls.append(s)
    monkeypatch.setattr("time.sleep", fake_sleep)
    limiter = RateLimiter(rate=10.0)  # 10/s => 0.1s between calls
    limiter.acquire()  # first call: no wait
    limiter.acquire()  # second call: should sleep ~0.1s
    assert calls and abs(calls[0] - 0.1) < 0.01
