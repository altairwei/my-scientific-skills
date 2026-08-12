# bioinformatics/locus-novelty/tests/test_gwas_catalog.py
import httpx
from apis import gwas_catalog


def _mock(payload):
    return httpx.Response(200, json=payload, request=httpx.Request("GET", "https://x/"))


_ASSOC = {
    "riskAlleles": [{"riskAlleleName": "rs3945628-C"}],
    "efoTraits": [{"trait": "polycystic ovary syndrome"}],
    "pvalueMantissa": 3, "pvalueExponent": -26, "pvalue": 3.87554e-26,
    "loci": [{"authorReportedGenes": [{"geneName": "DENND1A"}]}],
}


def test_snp_associations_uses_snp_exact_endpoint():
    seen = {}
    def handler(request):
        seen["path"] = request.url.path
        return _mock({"_embedded": {"associations": [_ASSOC]}, "page": {"totalElements": 1}})
    c = gwas_catalog._client(transport=httpx.MockTransport(handler))
    out = gwas_catalog.snp_associations("rs3945628", client=c)
    assert seen["path"].endswith("/singleNucleotidePolymorphisms/rs3945628/associations")
    assert out["total"] == 1
    a = out["associations"][0]
    assert a["lead_snp"] == "rs3945628"      # risk allele prefix stripped
    assert a["efo_traits"] == ["polycystic ovary syndrome"]
    assert a["pvalue"] == 3.87554e-26


def test_region_associations_uses_chromosome_start_end():
    seen = {}
    def handler(request):
        seen["chr"] = request.url.params["chromosome"]
        seen["start"] = request.url.params["start"]
        seen["end"] = request.url.params["end"]
        return _mock({"_embedded": {"associations": [_ASSOC]}, "page": {"totalElements": 1}})
    c = gwas_catalog._client(transport=httpx.MockTransport(handler))
    out = gwas_catalog.region_associations("9", 123273274, 124273274, client=c)
    assert seen["chr"] == "9" and seen["start"] == "123273274" and seen["end"] == "124273274"
    assert out["total"] == 1
