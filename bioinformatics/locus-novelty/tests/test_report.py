# bioinformatics/locus-novelty/tests/test_report.py
import json
from pathlib import Path
from report import build_candidates, write_outputs


def test_build_candidates_scores_each_locus():
    loci = [{
        "trait": "PCOS", "lead_snp": "rs3945628", "chr": "9", "pos_hg38": 123773274, "p": 3.87554e-26,
        "study_efo": "http://x/EFO_PCOS",
        "prior_reports": [
            {"catalog_lead": "rs3945628", "r2": 1.0, "efo_match_type": "exact", "efo_traits": ["PCOS"]},
            {"catalog_lead": "rs7", "r2": 0.05, "efo_match_type": "none", "efo_traits": ["BMI"]},
        ],
        "r2_threshold": 0.2, "locus_window": 500000,
    }]
    out = build_candidates(loci)
    row = out[0]
    assert row["snp_level_auto"] == "known"
    assert row["locus_level_auto"] == "known"
    assert row["combined_auto"] == "known"
    assert row["agent_judgment"] is None and row["user_confirmed"] is None


def test_write_outputs_creates_files(tmp_path):
    candidates = [{
        "trait": "PCOS", "lead_snp": "rs3945628", "chr": "9", "pos_hg38": 123773274, "p": 3.87554e-26,
        "snp_level_auto": "known", "locus_level_auto": "known", "combined_auto": "known",
        "prior_reports": [{"catalog_lead": "rs3945628", "r2": 1.0, "efo_match_type": "exact"}],
        "agent_judgment": None, "user_confirmed": None,
    }]
    write_outputs(candidates, tmp_path, commands=["locus_novelty.py --loci x.csv"])
    assert (tmp_path / "candidates.json").exists()
    assert (tmp_path / "draft_verdict.csv").exists()
    assert (tmp_path / "reproducibility" / "commands.sh").exists()
    assert "locus_novelty.py --loci x.csv" in (tmp_path / "reproducibility" / "commands.sh").read_text()
