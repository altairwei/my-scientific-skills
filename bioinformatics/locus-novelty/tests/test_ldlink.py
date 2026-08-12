# bioinformatics/locus-novelty/tests/test_ldlink.py
import httpx
from apis import ldlink


def test_ldproxy_r2_parses_tsv_and_sends_token():
    seen = {}
    def handler(request):
        seen["var"] = request.url.params["var"]
        seen["pop"] = request.url.params["pop"]
        seen["r2_d"] = request.url.params["r2_d"]
        seen["token"] = request.url.params["token"]
        tsv = "RS_Number\tPosition_GRCh38\tR2\tD_prime\tVariant_type\nrs1\t100\t0.9\t0.95\tSNV\nrs2\t200\t0.1\t0.3\tSNV\n"
        return httpx.Response(200, text=tsv, request=httpx.Request("GET", str(request.url)))
    c = ldlink._client(transport=httpx.MockTransport(handler), api_key="KEY123")
    out = ldlink.ldproxy_r2("rs3945628", "EUR", client=c)
    assert seen["var"] == "rs3945628" and seen["pop"] == "EUR" and seen["r2_d"] == "r2" and seen["token"] == "KEY123"
    assert out == {"rs1": 0.9, "rs2": 0.1}
