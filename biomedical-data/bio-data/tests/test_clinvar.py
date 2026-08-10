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
        return _mock({"result": {"uids": ["45595"], "45595": {"title": "NM_014000.3(VCL):c.2388G>A (p.Pro796=)", "germline_classification": "Pathogenic"}}})
    c = clinvar._client(transport=httpx.MockTransport(handler))
    data = clinvar.fetch_clinvar_variant("VCV000045595", client=c)
    assert seen["db"] == "clinvar"
    assert seen["id"] == "45595"  # VCV prefix stripped; numeric variation ID
    assert data["title"].startswith("NM_014000.3")
    assert data["germline_classification"] == "Pathogenic"
