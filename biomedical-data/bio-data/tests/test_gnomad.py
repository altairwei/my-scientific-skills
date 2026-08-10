# biomedical-data/bio-data/tests/test_gnomad.py
import httpx
from apis import gnomad


def _mock(payload):
    return httpx.Response(200, json=payload, request=httpx.Request("GET", "https://x/"))


def test_gnomad_variant_frequency_extracts_allele_counts():
    seen = {}
    def handler(request):
        seen["path"] = request.url.path
        return _mock({"genome": {"ac": 12, "an": 251, "ac_hom": 0},
                       "exome": {"ac": 5, "an": 100, "ac_hom": 0}})
    c = gnomad._client(transport=httpx.MockTransport(handler))
    data = gnomad.gnomad_variant_frequency("1-55051526-G-A", client=c)
    assert seen["path"].endswith("/api/variant/1-55051526-G-A")
    assert data["genome"]["ac"] == 12
    assert data["exome"]["an"] == 100
