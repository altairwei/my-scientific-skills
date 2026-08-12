# bioinformatics/locus-novelty/scripts/apis/ldlink.py
"""NCBI LDlink LDproxy — r2 of a query SNP vs proxies in a 500 kb window."""
from __future__ import annotations

import csv
import io
import os
from typing import Optional

import _common

BASE = "https://ldlink.nci.nih.gov/LDlinkRest"


def _client(transport=None, api_key=None) -> _common.HttpClient:
    return _common.HttpClient(BASE, rate=2.0, api_key=api_key or os.environ.get("NCBI_API_KEY"),
                              transport=transport, cache_dir=_common.cache_dir())


def ldproxy_r2(query_snp: str, pop: str = "EUR", window: int = 500000,
               client: Optional[_common.HttpClient] = None) -> dict:
    """Return {proxy_snp: r2} for the query SNP within `window` bp (1000G `pop`)."""
    c = client or _client()
    # LDproxy returns TSV; HttpClient.get expects JSON, so use the raw client.
    c._limiter.acquire()
    r = c._client.get("ldproxy", params={"var": query_snp, "pop": pop, "r2_d": "r2",
                                         "window": window, "genome_build": "grch38",
                                         "token": c._api_key or ""})
    r.raise_for_status()
    out = {}
    reader = csv.DictReader(io.StringIO(r.text), delimiter="\t")
    for row in reader:
        rs = row.get("RS_Number", "").strip()
        try:
            r2 = float(row.get("R2", ""))
        except (TypeError, ValueError):
            continue
        if rs:
            out[rs] = r2
    return out
