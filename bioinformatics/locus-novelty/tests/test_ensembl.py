# bioinformatics/locus-novelty/tests/test_ensembl.py
import httpx
from apis import ensembl


def _mock(payload):
    return httpx.Response(200, json=payload, request=httpx.Request("GET", "https://x/"))


def test_resolve_variant_returns_coords_alleles_consequence():
    seen = {}
    def handler(request):
        seen["path"] = request.url.path
        seen["ct"] = request.headers.get("Content-Type")
        return _mock({"seq_region_name": "9", "start": 123773274, "end": 123773274,
                       "allele_string": "C/G", "assembly_name": "GRCh38",
                       "most_severe_consequence": "missense_variant"})
    c = ensembl._client(transport=httpx.MockTransport(handler))
    v = ensembl.resolve_variant("rs3945628", client=c)
    assert seen["path"].endswith("/variation/human/rs3945628")
    assert seen["ct"] == "application/json"
    assert v["chr"] == "9" and v["pos_grch38"] == 123773274
    assert v["ref"] == "C" and "G" in v["alt_alleles"]
    assert v["most_severe_consequence"] == "missense_variant"
