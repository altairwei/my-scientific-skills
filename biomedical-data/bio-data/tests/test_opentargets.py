# biomedical-data/bio-data/tests/test_opentargets.py
import httpx
from apis import opentargets


def _mock(payload):
    return httpx.Response(200, json=payload, request=httpx.Request("POST", "https://x/"))


def test_search_targets():
    def handler(request):
        body = request.read().decode()
        assert "search" in body and "BRAF" in body
        return _mock({"data": {"search": {"hits": [{"id": "ENSG00000157764", "name": "BRAF"}], "total": 1}}})
    c = opentargets._client(transport=httpx.MockTransport(handler))
    data = opentargets.search_targets("BRAF", client=c)
    assert data["hits"][0]["name"] == "BRAF"


def test_target_associations():
    def handler(request):
        body = request.read().decode()
        assert "associations" in body
        return _mock({"data": {"associations": {"rows": [{"score": 0.9, "disease": {"id": "EFO_0003737"}}]}}})
    c = opentargets._client(transport=httpx.MockTransport(handler))
    data = opentargets.target_associations("ENSG00000157764", client=c)
    assert data["rows"][0]["score"] == 0.9
