# biomedical-data/bio-data/tests/test_dbsnp.py
import httpx
from apis import dbsnp


def _mock(payload):
    return httpx.Response(200, json=payload, request=httpx.Request("GET", "https://x/"))


def _client(handler):
    return dbsnp._client(transport=httpx.MockTransport(handler))


def test_search_dbsnp_region_builds_range_term():
    seen = {}
    def handler(request):
        seen["term"] = request.url.params["term"]
        return _mock({"esearchresult": {"idlist": ["rs1", "rs2"], "count": "2"}})
    data = dbsnp.search_dbsnp_region("1", 10000, 20000, client=_client(handler))
    assert "1[CHR]" in seen["term"]
    assert "10000[BP_POS] : 20000[BP_POS]" in seen["term"]
    assert data == {"rsids": ["rs1", "rs2"], "count": 2}


def test_dbsnp_get_rsids_returns_records():
    def handler(request):
        assert request.url.params["id"] == "1,2"  # rs prefix stripped; db=snp wants bare IDs
        return _mock({"result": {"uids": ["1", "2"], "1": {"snp_class": "snv", "CHRPOS": "1:12345"}, "2": {"snp_class": "snv", "CHRPOS": "1:67890"}}})
    data = dbsnp.dbsnp_get_rsids(["rs1", "rs2"], client=_client(handler))
    assert len(data["records"]) == 2
