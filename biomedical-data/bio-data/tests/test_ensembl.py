# biomedical-data/bio-data/tests/test_ensembl.py
import httpx
from apis import ensembl


def _mock(payload=None, text=None):
    req = httpx.Request("GET", "https://x/")
    if payload is not None:
        return httpx.Response(200, json=payload, request=req)
    return httpx.Response(200, text=text or "", request=req)


def test_query_ensembl_lookup_symbol():
    seen = {}
    def handler(request):
        seen["path"] = request.url.path
        seen["ua"] = request.headers.get("User-Agent")
        return _mock(payload={"id": "ENSG00000012048", "symbol": "BRCA1", "biotype": "protein_coding"})
    c = ensembl._client(transport=httpx.MockTransport(handler))
    data = ensembl.query_ensembl("lookup/symbol/human/BRCA1", client=c)
    assert seen["path"].endswith("/lookup/symbol/human/BRCA1")
    assert "mailto" in seen["ua"] or "@" in seen["ua"]
    assert data["symbol"] == "BRCA1"


def test_query_biomart_returns_tsv():
    seen = {}
    def handler(request: httpx.Request):
        seen["body"] = request.read().decode()
        return httpx.Response(200, text="BRCA1\tENSG00000012048\n",
                              request=httpx.Request("POST", str(request.url)))
    c = ensembl._mart_client(transport=httpx.MockTransport(handler))
    data = ensembl.query_biomart("<query></query>", client=c)
    assert "ENSG00000012048" in data
