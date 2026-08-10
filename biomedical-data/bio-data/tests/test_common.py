# biomedical-data/bio-data/tests/test_common.py
import httpx

from _common import RateLimiter, Retry, HttpClient


def _resp(status):
    return httpx.Response(status_code=status, text="", request=httpx.Request("GET", "https://x/"))


def _mock(status, payload=None, text=None):
    req = httpx.Request("GET", "https://x/")
    if payload is not None:
        return httpx.Response(status_code=status, json=payload, request=req)
    return httpx.Response(status_code=status, text=text or "", request=req)


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


def test_http_client_get_parses_json_and_sends_contact_email():
    seen = {}
    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers.get("User-Agent")
        seen["contact"] = request.headers.get("Contact-Email")
        seen["params"] = dict(request.url.params)
        return _mock(200, payload={"result": {"hello": "world"}})
    transport = httpx.MockTransport(handler)
    c = HttpClient("https://eutils.ncbi.nlm.nih.gov", contact_email="me@example.com", transport=transport)
    data = c.get("entrez/eutils/esummary.fcgi", params={"db": "pubmed", "id": "1"})
    assert data == {"result": {"hello": "world"}}
    assert seen["contact"] == "me@example.com"
    assert seen["params"]["db"] == "pubmed"


def test_http_client_caches_repeated_get(tmp_path):
    hits = {"n": 0}
    def handler(request):
        hits["n"] += 1
        return _mock(200, payload={"a": hits["n"]})
    transport = httpx.MockTransport(handler)
    c = HttpClient("https://x", transport=transport, cache_dir=str(tmp_path), cache_ttl=60)
    first = c.get("foo", params={"q": "1"})
    second = c.get("foo", params={"q": "1"})
    assert first == second == {"a": 1}
    assert hits["n"] == 1  # second served from cache


def test_http_client_raises_on_4xx_after_retry(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    def handler(request):
        return _mock(404, text="nope")
    transport = httpx.MockTransport(handler)
    c = HttpClient("https://x", transport=transport)
    try:
        c.get("missing")
        assert False, "expected raise"
    except httpx.HTTPStatusError:
        pass
