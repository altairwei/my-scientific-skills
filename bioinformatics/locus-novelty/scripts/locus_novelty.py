#!/usr/bin/env python3
# bioinformatics/locus-novelty/scripts/locus_novelty.py
# /// script
# requires-python = ">=3.10"
# dependencies = ["httpx"]
# ///
"""locus-novelty CLI: two-level known/novel assessment of GWAS lead loci."""
import argparse
import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import _common  # noqa: E402
import report  # noqa: E402
import ld_plink  # noqa: E402
from apis import ensembl, gwas_catalog, ols, ldlink  # noqa: E402


def _read_loci(csv_path: str) -> list[dict]:
    loci = []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            loci.append({
                "trait": row["trait"], "chr": row["chr"],
                "pos_hg38": int(row["pos_hg38"]), "lead_snp": row["lead_snp"],
                "p": float(row.get("p", "nan") or "nan"),
                "gene_region": row.get("gene_region", ""),
                "locus_type": row.get("locus_type", ""),
            })
    return loci


def _resolve_ld_source(args) -> str:
    if args.ld_source:
        return args.ld_source
    if args.ld_panel:
        return "plink"
    sys.stderr.write(
        "ERROR: --ld-source (plink|ldlink) or --ld-panel is required.\n"
        "If no local panel: ask the user whether to use LDlink (1000G pop, not strictly "
        "ancestry-matched) before invoking with --ld-source ldlink.\n")
    raise SystemExit(2)


def _compute_r2(study_snp, catalog_snps, args):
    if args.ld_source == "plink":
        pairs = ld_plink.plink_r2(study_snp, catalog_snps, args.ld_panel)
        return {b if a == study_snp else a: r2 for (a, b), r2 in pairs.items()}
    pop = args.ancestry
    proxies = ldlink.ldproxy_r2(study_snp, pop=pop)
    return {sn: proxies.get(sn) for sn in catalog_snps if proxies.get(sn) is not None}


def run_pipeline(loci: list[dict], out_dir: Path, ancestry: str, ld_source: str,
                 ld_panel: str | None, r2_threshold: float, locus_window: int,
                 commands: list[str]) -> list[dict]:
    enriched = []
    for loc in loci:
        rsid = loc["lead_snp"]
        var = ensembl.resolve_variant(rsid)
        snp_assocs = gwas_catalog.snp_associations(rsid)["associations"]
        reg_assocs = gwas_catalog.region_associations(loc["chr"],
                                                       loc["pos_hg38"] - locus_window,
                                                       loc["pos_hg38"] + locus_window)["associations"]
        all_assocs = snp_assocs + reg_assocs
        study_efo = ols.efo_lookup(loc["trait"])
        prior_reports = []
        catalog_snps = list({a["lead_snp"] for a in all_assocs if a.get("lead_snp") and a["lead_snp"] != rsid})
        r2_map = _compute_r2(rsid, catalog_snps, _Args(ld_source, ld_panel, ancestry)) if catalog_snps else {}
        for a in all_assocs:
            lead = a.get("lead_snp", "")
            if not lead or lead == rsid:
                continue
            prior_efo = None
            if a.get("efo_traits"):
                prior_efo = ols.efo_lookup(a["efo_traits"][0])
            prior_reports.append({
                "catalog_lead": lead,
                "r2": r2_map.get(lead),
                "efo_traits": a.get("efo_traits", []),
                "efo_match_type": ols.efo_distance(study_efo, prior_efo),
            })
        loc["study_efo"] = study_efo
        loc["prior_reports"] = prior_reports
        loc["r2_threshold"] = r2_threshold
        loc["locus_window"] = locus_window
        enriched.append(loc)
    candidates = report.build_candidates(enriched)
    report.write_outputs(candidates, out_dir, commands)
    return candidates


class _Args:
    def __init__(self, ld_source, ld_panel, ancestry):
        self.ld_source = ld_source; self.ld_panel = ld_panel; self.ancestry = ancestry


def main():
    ap = argparse.ArgumentParser(description="locus-novelty: two-level known/novel assessment")
    ap.add_argument("--loci", required=True, help="CSV of lead loci (trait,chr,pos_hg38,lead_snp,p)")
    ap.add_argument("--output", "-o", required=True, help="Output directory")
    ap.add_argument("--ancestry", default="EUR", help="1000G population for LDlink (EUR/AFR/AMR/EAS/SAS)")
    ap.add_argument("--ld-source", choices=["plink", "ldlink"], default=None)
    ap.add_argument("--ld-panel", default=None, help="PLINK bfile prefix (implies --ld-source plink)")
    ap.add_argument("--r2-threshold", type=float, default=0.2)
    ap.add_argument("--locus-window", type=int, default=500000, help="locus half-window in bp (default 500000)")
    args = ap.parse_args()

    ld_source = _resolve_ld_source(args)
    loci = _read_loci(args.loci)
    commands = [f"locus_novelty.py --loci {args.loci} --output {args.output} --ancestry {args.ancestry} "
                 f"--ld-source {ld_source} --r2-threshold {args.r2_threshold} --locus-window {args.locus_window}"]
    candidates = run_pipeline(loci, Path(args.output), args.ancestry, ld_source,
                              args.ld_panel, args.r2_threshold, args.locus_window, commands)
    print(f"Wrote {len(candidates)} loci to {args.output}/")
    print(f"  candidates.json + draft_verdict.csv + reproducibility/")
    print("Next: read candidates.json, apply EFO judgment per locus, present verdict table for user.")


if __name__ == "__main__":
    main()
