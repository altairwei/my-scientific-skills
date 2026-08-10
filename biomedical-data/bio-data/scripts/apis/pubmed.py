# biomedical-data/bio-data/scripts/apis/pubmed.py
"""PubMed tools: NCBI E-utilities (ESearch/ESummary/ELink) + Europe PMC full text."""
from __future__ import annotations

import os
from typing import Optional

import _common

NCBI_BASE = "https://eutils.ncbi.nlm.nih.gov"
PMC_BASE = "https://www.ebi.ac.uk/europepmc/webservices/rest"
_TOOL = "bio-data-mcp"


def _client(transport=None) -> _common.HttpClient:
    key = os.environ.get("NCBI_API_KEY")
    return _common.HttpClient(
        NCBI_BASE,
        contact_email=os.environ.get("NCBI_CONTACT_EMAIL"),
        rate=(10.0 if key else 3.0),
        api_key=key,
        transport=transport,
        cache_dir=_common.cache_dir(),
    )


def _pmc_client(transport=None) -> _common.HttpClient:
    return _common.HttpClient(PMC_BASE, rate=3.0, transport=transport,
                              cache_dir=_common.cache_dir())


def search_pubmed(query: str, retmax: int = 20, client: Optional[_common.HttpClient] = None):
    c = client or _client()
    data = c.get("entrez/eutils/esearch.fcgi", {
        "db": "pubmed", "term": query, "retmax": retmax,
        "retmode": "json", "tool": _TOOL,
    })
    res = data["esearchresult"]
    return {"pmids": res.get("idlist", []), "count": int(res.get("count", 0))}


def fetch_pubmed(pmids: list[str], client: Optional[_common.HttpClient] = None):
    c = client or _client()
    data = c.get("entrez/eutils/esummary.fcgi", {
        "db": "pubmed", "id": ",".join(pmids), "retmode": "json", "tool": _TOOL,
    })
    result = data.get("result", {})
    uids = result.get("uids", [])
    return [dict(uid=u, **{k: v for k, v in result[u].items() if k != "uid"})
            for u in uids]


def find_related_articles(pmid: str, client: Optional[_common.HttpClient] = None):
    c = client or _client()
    data = c.get("entrez/eutils/elink.fcgi", {
        "dbfrom": "pubmed", "db": "pubmed", "id": pmid,
        "cmd": "neighbor", "retmode": "json", "tool": _TOOL,
    })
    related = []
    for ls in data.get("linksets", []):
        for db in ls.get("linksetdbs", []):
            related.extend(db.get("links", []))
    return {"related_pmids": related}


def fetch_pmc_fulltext(pmc_ids: list[str], client: Optional[_common.HttpClient] = None):
    c = client or _pmc_client()
    out = {}
    for pid in pmc_ids:
        bare = pid[3:] if pid.startswith("PMC") else pid
        path = f"{bare}/fullTextXML" if pid.startswith("PMC") else f"PMC{bare}/fullTextXML"
        try:
            c._limiter.acquire()
            r = c._client.get(path)  # Europe PMC fullTextXML returns XML
            if r.status_code == 404:
                out[pid] = None
            else:
                r.raise_for_status()
                out[pid] = r.text
        except Exception:
            out[pid] = None
    return out
