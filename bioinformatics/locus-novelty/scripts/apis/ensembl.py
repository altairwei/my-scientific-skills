# bioinformatics/locus-novelty/scripts/apis/ensembl.py
"""Ensembl REST variant resolution (rsID -> chr:pos/alleles/consequence)."""
from __future__ import annotations

import os
from typing import Optional

import _common

BASE = "https://rest.ensembl.org"


def _client(transport=None) -> _common.HttpClient:
    email = os.environ.get("NCBI_CONTACT_EMAIL", "anonymous@example.com")
    return _common.HttpClient(BASE, ua=f"locus-novelty/0.1 (mailto:{email})", rate=15.0,
                              transport=transport, cache_dir=_common.cache_dir(),
                              headers={"Content-Type": "application/json"})


def resolve_variant(rsid: str, client: Optional[_common.HttpClient] = None) -> dict:
    c = client or _client()
    data = c.get(f"variation/human/{rsid}")
    alleles = data.get("allele_string", "").split("/")  # e.g. "C/G" -> ["C","G"]
    ref = alleles[0] if alleles else ""
    alts = alleles[1:] if len(alleles) > 1 else []
    return {
        "rsid": rsid,
        "chr": data.get("seq_region_name", ""),
        "pos_grch38": data.get("start"),
        "ref": ref,
        "alt_alleles": alts,
        "allele_string": data.get("allele_string", ""),
        "most_severe_consequence": data.get("most_severe_consequence", ""),
        "assembly": data.get("assembly_name", ""),
    }
