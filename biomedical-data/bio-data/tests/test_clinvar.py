# biomedical-data/bio-data/tests/test_clinvar.py
import httpx
from apis import clinvar


def _mock(payload):
    return httpx.Response(200, json=payload, request=httpx.Request("GET", "https://x/"))


def test_fetch_clinvar_variant_returns_summary():
    seen = {}
    def handler(request):
        seen["db"] = request.url.params["db"]
        seen["id"] = request.url.params["id"]
        return _mock({"result": {"uids": ["672"], "672": {"title": "NM_007294.4(BRCA1):c.5266dup", "clinical_significance": "Pathogenic"}}})
    c = clinvar._client(transport=httpx.MockTransport(handler))
    data = clinvar.fetch_clinvar_variant("VCV000045595", client=c)
    assert seen["db"] == "clinvar"
    assert seen["id"] == "VCV000045595"
    assert data["title"].startswith("NM_007294.4")
    assert data["clinical_significance"] == "Pathogenic"
