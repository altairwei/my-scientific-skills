# biomedical-data/bio-data/scripts/apis/dbsnp.py
"""dbSNP tools: region rsID search + batch rsID records (NCBI E-utilities, db=snp)."""
from __future__ import annotations

import os
from typing import Optional

import _common

BASE = "https://eutils.ncbi.nlm.nih.gov"
_TOOL = "bio-data-mcp"


def _client(transport=None) -> _common.HttpClient:
    key = os.environ.get("NCBI_API_KEY")
    return _common.HttpClient(
        BASE, contact_email=os.environ.get("NCBI_CONTACT_EMAIL"),
        rate=(10.0 if key else 3.0), api_key=key, transport=transport,
        cache_dir=_common.cache_dir())


def search_dbsnp_region(chrom: str, start: int, stop: int, assembly: str = "GRCh38",
                        max_rsids: int = 200, client: Optional[_common.HttpClient] = None):
    c = client or _client()
    term = f"{chrom}[CHR] AND {start}[BP_POS] : {stop}[BP_POS]"
    data = c.get("entrez/eutils/esearch.fcgi", {
        "db": "snp", "term": term, "retmax": max_rsids,
        "retmode": "json", "tool": _TOOL,
    })
    res = data["esearchresult"]
    return {"rsids": res.get("idlist", []), "count": int(res.get("count", 0))}


def dbsnp_get_rsids(rsids: list[str], client: Optional[_common.HttpClient] = None):
    c = client or _client()
    # db=snp esummary wants bare numeric IDs (live-verified: id=rs1800722
    # returns [], id=1800722 returns the record) — strip the rs prefix.
    ids = ",".join(r[2:] if r.startswith("rs") else r for r in rsids)
    data = c.get("entrez/eutils/esummary.fcgi", {
        "db": "snp", "id": ids, "retmode": "json", "tool": _TOOL,
    })
    result = data.get("result", {})
    uids = result.get("uids", [])
    return {"records": [result[u] for u in uids]}
