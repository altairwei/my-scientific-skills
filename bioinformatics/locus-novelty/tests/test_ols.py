# bioinformatics/locus-novelty/tests/test_ols.py
import httpx
from apis import ols


def _mock(payload):
    return httpx.Response(200, json=payload, request=httpx.Request("GET", "https://x/"))


def test_efo_lookup_returns_best_iri():
    seen = {}
    def handler(request):
        seen["q"] = request.url.params["q"]
        return _mock({"response": {"docs": [{"iri": "http://www.ebi.ac.uk/efo/EFO_0000001", "label": "polycystic ovary syndrome"}]}})
    c = ols._client(transport=httpx.MockTransport(handler))
    iri = ols.efo_lookup("polycystic ovary syndrome", client=c)
    assert iri == "http://www.ebi.ac.uk/efo/EFO_0000001"
    assert seen["q"] == "polycystic ovary syndrome"


def test_efo_lookup_returns_none_when_no_match():
    def handler(request):
        return _mock({"response": {"docs": []}})
    c = ols._client(transport=httpx.MockTransport(handler))
    assert ols.efo_lookup("nonexistent trait xyz", client=c) is None


def test_efo_distance_exact_for_same_iri():
    assert ols.efo_distance("http://x/EFO_1", "http://x/EFO_1") == "exact"


def test_efo_distance_parent_when_prior_is_ancestor(monkeypatch):
    calls = {"ancestors": 0}
    def fake_ancestors(iri, client=None):
        calls["ancestors"] += 1
        return ["http://x/ANC"]  # study's ancestors
    monkeypatch.setattr(ols, "ancestors", fake_ancestors)
    assert ols.efo_distance("http://x/EFO_study", "http://x/ANC") == "parent"


def test_efo_distance_none_when_unrelated(monkeypatch):
    monkeypatch.setattr(ols, "ancestors", lambda iri, client=None: ["http://x/OTHER"])
    assert ols.efo_distance("http://x/EFO_study", "http://x/EFO_prior") == "none"
