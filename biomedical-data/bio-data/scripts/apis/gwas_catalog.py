# biomedical-data/bio-data/scripts/apis/gwas_catalog.py
"""GWAS Catalog association search (EMBL-EBI REST)."""
from __future__ import annotations

from typing import Optional

import _common

BASE = "https://www.ebi.ac.uk/gwas/rest/api"


def _client(transport=None) -> _common.HttpClient:
    return _common.HttpClient(BASE, rate=3.0, transport=transport,
                              cache_dir=_common.cache_dir())


def search_gwas_catalog(query: str, size: int = 20, client: Optional[_common.HttpClient] = None):
    c = client or _client()
    data = c.get("associations", {"q": query, "size": size})
    embedded = data.get("_embedded", {})
    return {
        "associations": embedded.get("associations", []),
        "total": data.get("page", {}).get("totalElements", 0),
    }
