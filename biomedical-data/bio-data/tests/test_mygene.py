# biomedical-data/bio-data/tests/test_mygene.py
import httpx
from apis import mygene


def _mock(payload):
    return httpx.Response(200, json=payload, request=httpx.Request("GET", "https://x/"))


def test_query_genes_by_symbol():
    seen = {}
    def handler(request):
        seen["q"] = request.url.params["q"]
        seen["fields"] = request.url.params["fields"]
        return _mock({"hits": [{"_id": "672", "symbol": "BRCA1"}], "total": 1})
    c = mygene._client(transport=httpx.MockTransport(handler))
    data = mygene.query_genes("symbol:BRCA1", client=c)
    assert data == {"hits": [{"_id": "672", "symbol": "BRCA1"}], "total": 1}
    assert seen["q"] == "symbol:BRCA1"
