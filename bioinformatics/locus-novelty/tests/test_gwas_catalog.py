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

_STUDY = {
    "accessionId": "GCST1",
    "publicationInfo": {"pubmedId": "111", "title": "T", "publication": "J",
                        "publicationDate": "2021-11-13", "author": {"fullname": "Author A"}},
    "initialSampleSize": "100 cases",
    "replicationSampleSize": None,
    "ancestries": [
        {"type": "initial", "numberOfIndividuals": 141355,
         "ancestralGroups": [{"ancestralGroup": "European"}],
         "countryOfRecruitment": [{"countryName": "Finland"}]},
        {"type": "replication", "numberOfIndividuals": 233398,
         "ancestralGroups": [{"ancestralGroup": "European"}],
         "countryOfRecruitment": [{"countryName": "Estonia"}]},
    ],
}


def _handler(seen):
    def handler(request):
        path = request.url.path
        seen.setdefault("paths", []).append(path)
        if path.endswith("/study"):
            return _mock(_STUDY)
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
    assert a["lead_snp"] == "rs3945628"
    assert a["efo_traits"] == ["polycystic ovary syndrome"]
    assert a["association_id"] == "93407956"
    assert a["pvalue"] == 3.87554e-26


def test_normalise_includes_study_provenance():
    seen = {}
    c = gwas_catalog._client(transport=httpx.MockTransport(_handler(seen)))
    a = gwas_catalog.snp_associations("rs3945628", client=c)["associations"][0]
    s = a["study"]
    assert s["accession"] == "GCST1"
    assert s["pmid"] == "111"
    assert s["title"] == "T"
    assert s["author"] == "Author A"
    assert s["journal"] == "J"
    assert s["year"] == 2021
    assert s["n_initial"] == "100 cases"
    assert s["ancestries"][0]["ancestral_groups"] == ["European"]
    assert s["ancestries"][0]["country"] == ["Finland"]
    assert s["ancestries"][1]["type"] == "replication"
    assert s["abstract"] is None
    assert any(p.endswith("/associations/93407956/study") for p in seen["paths"])


def test_region_associations_via_snp_window_finder():
    seen = {}
    c = gwas_catalog._client(transport=httpx.MockTransport(_handler(seen)))
    out = gwas_catalog.region_associations("9", 123273274, 124273274, client=c)
    assert any("/findByChromBpLocationRange" in p for p in seen["paths"])
    assert out["total"] == 1
    assert out["associations"][0]["lead_snp"] == "rs3945628"
    assert out["truncated"] is False
