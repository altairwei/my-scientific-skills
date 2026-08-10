# biomedical-data/bio-data/scripts/apis/ensembl.py
"""Ensembl tools: REST lookup + BioMart (POST XML → TSV)."""
from __future__ import annotations

import os
from typing import Optional

import _common

REST_BASE = "https://rest.ensembl.org"
MART_BASE = "https://www.ensembl.org/biomart"


def _polite_ua() -> str:
    email = os.environ.get("NCBI_CONTACT_EMAIL", "anonymous@example.com")
    return f"bio-data-mcp/0.1 (mailto:{email})"


def _client(transport=None) -> _common.HttpClient:
    return _common.HttpClient(REST_BASE, ua=_polite_ua(), rate=15.0,
                              transport=transport,
                              cache_dir=_common.cache_dir())


def _mart_client(transport=None) -> _common.HttpClient:
    return _common.HttpClient(MART_BASE, ua=_polite_ua(), rate=1.0, transport=transport)


def query_ensembl(path: str, params: Optional[dict] = None,
                  client: Optional[_common.HttpClient] = None):
    c = client or _client()
    return c.get(path, params=params)


def query_biomart(xml_query: str, client: Optional[_common.HttpClient] = None):
    c = client or _mart_client()
    c._limiter.acquire()
    r = c._client.post("martservice", data={"query": xml_query})
    r.raise_for_status()
    return r.text  # TSV
