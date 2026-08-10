# biomedical-data/bio-data/scripts/apis/mygene.py
"""MyGene.info gene query."""
from __future__ import annotations

from typing import Optional

import _common

BASE = "https://mygene.info/v3"


def _client(transport=None) -> _common.HttpClient:
    return _common.HttpClient(BASE, rate=5.0, transport=transport,
                              cache_dir=_common.cache_dir())


def query_genes(query: str, fields: str = "symbol,entrezgene,ensembl.gene,name",
                size: int = 10, client: Optional[_common.HttpClient] = None):
    c = client or _client()
    data = c.get("query", {"q": query, "fields": fields, "size": size})
    return {"hits": data.get("hits", []), "total": data.get("total", 0)}
