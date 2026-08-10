# biomedical-data/bio-data/tests/test_pubmed.py
import httpx
from apis import pubmed


def _mock(status, payload=None, text=None):
    req = httpx.Request("GET", "https://x/")
    if payload is not None:
        return httpx.Response(status_code=status, json=payload, request=req)
    return httpx.Response(status_code=status, text=text or "", request=req)


def _ncbi_client(handler):
    transport = httpx.MockTransport(handler)
    return pubmed._client(transport=transport)


def test_search_pubmed_returns_pmids_and_count():
    def handler(request):
        assert request.url.path.endswith("/esearch.fcgi")
        assert request.url.params["term"] == "BRCA1"
        assert request.url.params["retmode"] == "json"
        return _mock(200, payload={"esearchresult": {"idlist": ["1", "2"], "count": "2"}})
    data = pubmed.search_pubmed("BRCA1", client=_ncbi_client(handler))
    assert data == {"pmids": ["1", "2"], "count": 2}


def test_fetch_pubmed_returns_summaries():
    def handler(request):
        assert request.url.path.endswith("/esummary.fcgi")
        assert request.url.params["id"] == "1,2"
        return _mock(200, payload={"result": {"uids": ["1", "2"], "1": {"title": "A"}, "2": {"title": "B"}}})
    data = pubmed.fetch_pubmed(["1", "2"], client=_ncbi_client(handler))
    assert data == [{"uid": "1", "title": "A"}, {"uid": "2", "title": "B"}]


def test_find_related_articles_returns_pmids():
    def handler(request):
        assert request.url.path.endswith("/elink.fcgi")
        assert request.url.params["cmd"] == "neighbor"
        return _mock(200, payload={"linksets": [{"linksetdbs": [{"links": ["9", "8"]}]}]})
    data = pubmed.find_related_articles("1", client=_ncbi_client(handler))
    assert data == {"related_pmids": ["9", "8"]}


def test_fetch_pmc_fulltext_returns_xml():
    def handler(request):
        assert "fullTextXML" in request.url.path
        return httpx.Response(200, text="<article>full text</article>",
                              request=httpx.Request("GET", str(request.url)))
    c = pubmed._pmc_client(transport=httpx.MockTransport(handler))
    data = pubmed.fetch_pmc_fulltext(["PMC123"], client=c)
    assert data == {"PMC123": "<article>full text</article>"}
