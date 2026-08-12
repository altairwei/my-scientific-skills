# bioinformatics/locus-novelty/tests/test_common.py
import httpx
from _common import RateLimiter, Retry, HttpClient, cache_dir


def _mock(status, payload=None, text=None):
    req = httpx.Request("GET", "https://x/")
    if payload is not None:
        return httpx.Response(status_code=status, json=payload, request=req)
    return httpx.Response(status_code=status, text=text or "", request=req)


def test_rate_limiter_paces_calls(monkeypatch):
    calls = []
    monkeypatch.setattr("time.sleep", lambda s: calls.append(s))
    lim = RateLimiter(rate=10.0)  # 0.1s between calls
    lim.acquire(); lim.acquire()
    assert calls and abs(calls[0] - 0.1) < 0.01


def test_retry_retries_on_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    n = {"i": 0}
    def fn():
        n["i"] += 1
        return _mock(200) if n["i"] == 2 else _mock(429)
    r = Retry(max_attempts=4, base=0.0).call(fn)
    assert r.status_code == 200 and n["i"] == 2


def test_http_client_get_parses_json_and_sends_contact_email():
    seen = {}
    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers.get("User-Agent")
        seen["params"] = dict(request.url.params)
        return _mock(200, payload={"r": 1})
    c = HttpClient("https://eutils.ncbi.nlm.nih.gov", contact_email="me@example.com",
                   transport=httpx.MockTransport(handler))
    assert c.get("entrez/eutils/esummary.fcgi", params={"db": "pubmed"}) == {"r": 1}
    assert seen["ua"] and seen["params"]["db"] == "pubmed"


def test_http_client_caches_repeated_get(tmp_path):
    hits = {"n": 0}
    def handler(request):
        hits["n"] += 1
        return _mock(200, payload={"a": hits["n"]})
    c = HttpClient("https://x", transport=httpx.MockTransport(handler),
                   cache_dir=str(tmp_path), cache_ttl=60)
    a = c.get("foo", params={"q": "1"}); b = c.get("foo", params={"q": "1"})
    assert a == b == {"a": 1} and hits["n"] == 1


def test_cache_dir_none_when_env_unset(monkeypatch):
    monkeypatch.delenv("CLAUDE_PLUGIN_DATA", raising=False)
    assert cache_dir() is None
