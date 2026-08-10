# biomedical-data/bio-data/tests/test_gwas_catalog.py
import httpx
from apis import gwas_catalog


def _mock(payload):
    return httpx.Response(200, json=payload, request=httpx.Request("GET", "https://x/"))


def test_search_gwas_catalog_by_trait():
    seen = {}
    def handler(request):
        seen["q"] = request.url.params["q"]
        return _mock({"_embedded": {"associations": [{"risk_allele": "A", "p_value": 1e-8}]}, "page": {"totalElements": 1}})
    c = gwas_catalog._client(transport=httpx.MockTransport(handler))
    data = gwas_catalog.search_gwas_catalog("crohn disease", client=c)
    assert seen["q"] == "crohn disease"
    assert len(data["associations"]) == 1
