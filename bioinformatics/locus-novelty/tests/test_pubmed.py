# bioinformatics/locus-novelty/tests/test_pubmed.py
import httpx
from apis import pubmed


XML = """<?xml version="1.0"?>
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation><PMID>111</PMID>
      <Article><Abstract>
        <AbstractText Label="BACKGROUND">We studied PCOS.</AbstractText>
        <AbstractText Label="RESULTS">Signal replicated.</AbstractText>
      </Abstract></Article>
    </MedlineCitation>
  </PubmedArticle>
  <PubmedArticle>
    <MedlineCitation><PMID>222</PMID>
      <Article></Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>"""


def test_parse_joins_abstract_chunks_and_handles_missing():
    out = pubmed._parse(XML)
    assert out["111"] == "We studied PCOS. Signal replicated."
    assert out["222"] == ""   # no Abstract element


def test_abstracts_sends_efetch_and_returns_map():
    seen = {}
    def handler(request):
        seen["path"] = request.url.path
        seen["id"] = request.url.params["id"]
        seen["db"] = request.url.params["db"]
        return httpx.Response(200, text=XML, request=httpx.Request("GET", str(request.url)))
    c = pubmed._client(transport=httpx.MockTransport(handler))
    out = pubmed.abstracts(["111", "222"], client=c)
    assert seen["db"] == "pubmed"
    assert seen["id"] == "111,222"
    assert seen["path"].endswith("/efetch.fcgi")
    assert out["111"] == "We studied PCOS. Signal replicated."
    assert out["222"] == ""


def test_abstracts_empty_input_returns_empty_without_call():
    seen = {"called": False}
    def handler(request):
        seen["called"] = True
        return httpx.Response(200, text="")
    c = pubmed._client(transport=httpx.MockTransport(handler))
    assert pubmed.abstracts([], client=c) == {}
    assert seen["called"] is False
