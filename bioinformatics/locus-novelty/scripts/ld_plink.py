# bioinformatics/locus-novelty/scripts/ld_plink.py
"""Local PLINK --r2 wrapper for ancestry-matched LD between a study lead and cataloged leads."""
from __future__ import annotations

import csv
import subprocess
from pathlib import Path
from typing import Optional


def _run_subprocess(args: list[str]) -> int:
    return subprocess.run(args, capture_output=True).returncode


def plink_r2(study_snp: str, catalog_snps: list[str], bfile: str,
             tmp_dir: Optional[Path] = None) -> dict[tuple[str, str], float]:
    """Compute r2 between study_snp and each catalog SNP via PLINK --r2.

    Returns {(snp_a, snp_b): r2} for all pairs in the .ld output involving study_snp.
    """
    tmp_dir = Path(tmp_dir) if tmp_dir else Path("/tmp")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    snps_file = tmp_dir / "extract_snps.txt"
    snps_file.write_text("\n".join([study_snp] + catalog_snps) + "\n")
    out_prefix = tmp_dir / "locus_novelty_r2"
    args = [
        "plink", "--bfile", bfile, "--r2", "inter-chr",
        "--extract", str(snps_file),
        "--ld-window-r2", "0", "--ld-window", "999999", "--ld-window-kb", "1000",
        "--out", str(out_prefix),
    ]
    rc = _run_subprocess(args)
    if rc != 0 or not (out_prefix.with_suffix(".ld")).exists():
        raise RuntimeError(f"plink --r2 failed (rc={rc}); check plink is installed and bfile path")
    pairs: dict[tuple[str, str], float] = {}
    with open(out_prefix.with_suffix(".ld")) as f:
        for row in csv.DictReader(f, delimiter="\t"):
            a, b = row.get("SNP_A", ""), row.get("SNP_B", "")
            try:
                r2 = float(row.get("R2", ""))
            except (TypeError, ValueError):
                continue
            if study_snp in (a, b):
                pairs[(a, b)] = r2
    return pairs
