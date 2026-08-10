# biomedical-data/bio-data/scripts/apis/clinvar.py
"""ClinVar variant clinical interpretation (NCBI E-utilities, db=clinvar)."""
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


def fetch_clinvar_variant(accession: str, client: Optional[_common.HttpClient] = None):
    c = client or _client()
    # esummary db=clinvar takes the bare numeric variation ID, not the VCV
    # accession (VCV000045595 -> 45595). Normalize: keep digits, drop zeros.
    digits = "".join(ch for ch in accession if ch.isdigit())
    vid = str(int(digits)) if digits else accession
    data = c.get("entrez/eutils/esummary.fcgi", {
        "db": "clinvar", "id": vid, "retmode": "json", "tool": _TOOL,
    })
    result = data.get("result", {})
    uids = result.get("uids", [])
    if not uids:
        return {"accession": accession, "found": False}
    entry = result[uids[0]]
    return {
        "accession": accession,
        "found": True,
        "title": entry.get("title"),
        "germline_classification": entry.get("germline_classification"),
        "uid": uids[0],
    }
