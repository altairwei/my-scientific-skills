# bioinformatics/locus-novelty/tests/test_gwas_catalog.py
import httpx
from apis import gwas_catalog


def _mock(payload):
    return httpx.Response(200, json=payload, request=httpx.Request("GET", "https://x/"))


_ASSOC = {
    "pvalueMantissa": 3, "pvalueExponent": -26, "pvalue": 3.87554e-26,
    "loci": [{
        "strongestRiskAlleles": [{"riskAlleleName": "rs3945628-C"}],
        "authorReportedGenes": [{"geneName": "DENND1A"}],
    }],
    "_links": {"self": {"href": "https://www.ebi.ac.uk/gwas/rest/api/associations/93407956"}},
}


def _handler(seen):
    def handler(request):
        path = request.url.path
        seen.setdefault("paths", []).append(path)
        if path.endswith("/efoTraits"):
            return _mock({"_embedded": {"efoTraits": [{"trait": "polycystic ovary syndrome"}]}})
        if "/findByChromBpLocationRange" in path:
            return _mock({"_embedded": {"singleNucleotidePolymorphisms": [{"rsId": "rs1752167"}]},
                          "page": {"totalElements": 1}})
        return _mock({"_embedded": {"associations": [_ASSOC]}, "page": {"totalElements": 1}})
    return handler


def test_snp_associations_uses_snp_exact_endpoint():
    seen = {}
    c = gwas_catalog._client(transport=httpx.MockTransport(_handler(seen)))
    out = gwas_catalog.snp_associations("rs3945628", client=c)
    assert seen["paths"][0].endswith("/singleNucleotidePolymorphisms/rs3945628/associations")
    assert out["total"] == 1
    a = out["associations"][0]
    assert a["lead_snp"] == "rs3945628"      # strongest risk allele, allele suffix stripped
    assert a["efo_traits"] == ["polycystic ovary syndrome"]
    assert a["association_id"] == "93407956"
    assert a["pvalue"] == 3.87554e-26


def test_region_associations_via_snp_window_finder():
    seen = {}
    c = gwas_catalog._client(transport=httpx.MockTransport(_handler(seen)))
    out = gwas_catalog.region_associations("9", 123273274, 124273274, client=c)
    assert any("/findByChromBpLocationRange" in p for p in seen["paths"])
    assert out["total"] == 1
    assert out["associations"][0]["lead_snp"] == "rs3945628"
    assert out["truncated"] is False
