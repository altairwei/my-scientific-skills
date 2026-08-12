# bioinformatics/locus-novelty/scripts/apis/gwas_catalog.py
"""GWAS Catalog REST: SNP-exact + region association lookup."""
from __future__ import annotations

from typing import Optional

import _common

BASE = "https://www.ebi.ac.uk/gwas/rest/api"


def _client(transport=None) -> _common.HttpClient:
    return _common.HttpClient(BASE, rate=3.0, transport=transport, cache_dir=_common.cache_dir())


def _normalise(a: dict) -> dict:
    risk = (a.get("riskAlleles") or [{}])[0].get("riskAlleleName", "")
    lead = risk.split("-")[0] if risk else ""           # "rs3945628-C" -> "rs3945628"
    traits = [t.get("trait", "") for t in a.get("efoTraits", [])]
    genes = []
    loci = a.get("loci") or []
    if loci:
        genes = [g.get("geneName", "") for g in loci[0].get("authorReportedGenes", [])]
    return {
        "lead_snp": lead,
        "efo_traits": traits,
        "reported_genes": genes,
        "pvalue": a.get("pvalue"),
        "pvalue_mantissa": a.get("pvalueMantissa"),
        "pvalue_exponent": a.get("pvalueExponent"),
    }


def snp_associations(rsid: str, max_hits: int = 100, client: Optional[_common.HttpClient] = None) -> dict:
    c = client or _client()
    data = c.get(f"singleNucleotidePolymorphisms/{rsid}/associations", {"size": max_hits})
    assocs = (data.get("_embedded") or {}).get("associations", [])
    return {"source": "gwas_catalog_snp", "rsid": rsid,
            "total": data.get("page", {}).get("totalElements", len(assocs)),
            "associations": [_normalise(a) for a in assocs]}


def region_associations(chr_: str, start: int, end: int, max_hits: int = 200,
                        client: Optional[_common.HttpClient] = None) -> dict:
    c = client or _client()
    data = c.get("associations", {"chromosome": str(chr_), "start": start, "end": end, "size": max_hits})
    assocs = (data.get("_embedded") or {}).get("associations", [])
    return {"source": "gwas_catalog_region", "chr": chr_, "start": start, "end": end,
            "total": data.get("page", {}).get("totalElements", len(assocs)),
            "associations": [_normalise(a) for a in assocs]}
