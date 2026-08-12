# bioinformatics/locus-novelty/scripts/apis/gwas_catalog.py
"""GWAS Catalog REST: SNP-exact + region association lookup."""
from __future__ import annotations

from typing import Optional

import _common

BASE = "https://www.ebi.ac.uk/gwas/rest/api"


def _client(transport=None) -> _common.HttpClient:
    return _common.HttpClient(BASE, rate=3.0, transport=transport, cache_dir=_common.cache_dir())


def _association_id(a: dict) -> str:
    href = ((a.get("_links") or {}).get("self") or {}).get("href", "")
    return href.rstrip("/").rsplit("/", 1)[-1]


def _lead_snp(a: dict) -> str:
    loci = a.get("loci") or []
    if not loci:
        return ""
    sra = loci[0].get("strongestRiskAlleles") or []
    if not sra:
        return ""
    risk = sra[0].get("riskAlleleName", "")
    return risk.split("-")[0] if risk else ""            # "rs3945628-C" -> "rs3945628"


def _efo_traits(a: dict, client: Optional[_common.HttpClient]) -> list[str]:
    aid = _association_id(a)
    if not aid or client is None:
        return []
    data = client.get(f"associations/{aid}/efoTraits")
    return [t.get("trait", "") for t in (data.get("_embedded") or {}).get("efoTraits", [])]


def _normalise(a: dict, client: Optional[_common.HttpClient] = None) -> dict:
    loci = a.get("loci") or []
    genes = []
    if loci:
        genes = [g.get("geneName", "") for g in loci[0].get("authorReportedGenes", [])]
    return {
        "association_id": _association_id(a),
        "lead_snp": _lead_snp(a),
        "efo_traits": _efo_traits(a, client),
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
            "associations": [_normalise(a, c) for a in assocs]}


def region_associations(chr_: str, start: int, end: int, max_snps: int = 100,
                        client: Optional[_common.HttpClient] = None) -> dict:
    """Cataloged associations whose SNPs fall in [start, end] on `chr_`.

    The catalog has no association-level region finder, so this queries SNPs in
    the window (findByChromBpLocationRange) then fetches each SNP's associations,
    deduplicating by association id. `max_snps` caps the SNPs processed
    (`truncated=True` when the window holds more).
    """
    c = client or _client()
    data = c.get("singleNucleotidePolymorphisms/search/findByChromBpLocationRange",
                 {"chrom": str(chr_), "bpStart": start, "bpEnd": end, "size": max_snps})
    snps = (data.get("_embedded") or {}).get("singleNucleotidePolymorphisms", [])
    total_snps = (data.get("page") or {}).get("totalElements", len(snps))
    seen: set[str] = set()
    out: list[dict] = []
    for s in snps[:max_snps]:
        rsid = s.get("rsId")
        if not rsid:
            continue
        adata = c.get(f"singleNucleotidePolymorphisms/{rsid}/associations", {"size": 50})
        for a in (adata.get("_embedded") or {}).get("associations", []):
            aid = _association_id(a)
            if aid and aid not in seen:
                seen.add(aid)
                out.append(_normalise(a, c))
    return {"source": "gwas_catalog_region", "chr": chr_, "start": start, "end": end,
            "region_snp_count": total_snps, "truncated": total_snps > max_snps,
            "total": len(out), "associations": out}
