# biomedical-data/bio-data/tests/test_gnomad.py
import httpx
from apis import gnomad


def _mock(payload):
    return httpx.Response(200, json=payload, request=httpx.Request("POST", "https://x/"))


def test_gnomad_variant_frequency_extracts_allele_counts():
    seen = {}
    def handler(request):
        body = request.read().decode()
        assert "variantId" in body and "gnomad_r4" in body and "1-55051526-G-A" in body
        return _mock({"data": {"variant": {"variant_id": "1-55051526-G-A",
                                           "genome": {"ac": 12, "an": 251, "af": 0.047},
                                           "exome": {"ac": 5, "an": 100, "af": 0.05}}}})
    c = gnomad._client(transport=httpx.MockTransport(handler))
    data = gnomad.gnomad_variant_frequency("1-55051526-G-A", client=c)
    assert data["genome"]["ac"] == 12
    assert data["exome"]["an"] == 100
