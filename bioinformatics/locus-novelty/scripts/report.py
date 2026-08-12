# bioinformatics/locus-novelty/scripts/report.py
"""Assemble per-locus candidates + write candidates.json / draft_verdict.csv / reproducibility/."""
from __future__ import annotations

import csv
import json
from pathlib import Path

from score import snp_level_verdict, locus_level_verdict, combine


def build_candidates(loci: list[dict]) -> list[dict]:
    out = []
    for loc in loci:
        priors = loc.get("prior_reports", [])
        snp = snp_level_verdict(priors, loc.get("r2_threshold", 0.2))
        locus = locus_level_verdict(priors)
        out.append({
            "trait": loc["trait"], "lead_snp": loc["lead_snp"], "chr": loc["chr"],
            "pos_hg38": loc["pos_hg38"], "p": loc.get("p"),
            "study_efo": loc.get("study_efo"),
            "prior_reports": priors,
            "snp_level_auto": snp, "locus_level_auto": locus, "combined_auto": combine(snp, locus),
            "agent_judgment": None, "user_confirmed": None,
        })
    return out


def write_outputs(candidates: list[dict], out_dir: Path, commands: list[str]):
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "candidates.json").write_text(json.dumps(candidates, indent=2, default=str))
    cols = ["trait", "lead_snp", "chr", "pos_hg38", "p", "snp_level_auto", "locus_level_auto",
            "combined_auto", "agent_judgment", "user_confirmed"]
    with open(out_dir / "draft_verdict.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for c in candidates:
            w.writerow({k: c.get(k) for k in cols})
    rep = out_dir / "reproducibility"
    rep.mkdir(exist_ok=True)
    (rep / "commands.sh").write_text("\n".join("# " + c for c in commands) + "\n")
