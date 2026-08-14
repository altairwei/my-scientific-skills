# bioinformatics/locus-novelty/tests/test_report.py
import json
from pathlib import Path
from report import build_candidates, write_outputs


def test_build_candidates_scores_each_locus_and_summarizes_evidence():
    loci = [{
        "trait": "PCOS", "lead_snp": "rs3945628", "chr": "9", "pos_hg38": 123773274, "p": 3.87554e-26,
        "study_efo": "http://x/EFO_PCOS",
        "prior_reports": [
            {"catalog_lead": "rs3945628", "r2": 1.0, "efo_match_type": "exact", "efo_traits": ["PCOS"],
             "study": {"accession": "GCST1", "pmid": "111", "year": 2021,
                       "ancestries": [{"type": "initial", "n": 141355, "ancestral_groups": ["European"], "country": ["Finland"]}]}},
            {"catalog_lead": "rs7", "r2": 0.05, "efo_match_type": "none", "efo_traits": ["BMI"], "study": {}},
        ],
        "r2_threshold": 0.2, "locus_window": 500000,
    }]
    out = build_candidates(loci)
    row = out[0]
    assert row["snp_level_auto"] == "known"
    assert row["locus_level_auto"] == "known"
    assert row["combined_auto"] == "known"
    assert row["evidence_summary"]["n_studies"] == 1      # only GCST1 has an accession
    assert row["evidence_summary"]["ancestry_set"] == ["European"]
    assert row["evidence_summary"]["max_n"] == 141355
    assert row["evidence_level"] is None                 # agent fills this
    assert row["agent_judgment"] is None and row["user_confirmed"] is None


def test_write_outputs_creates_files_with_evidence_column(tmp_path):
    candidates = [{
        "trait": "PCOS", "lead_snp": "rs3945628", "chr": "9", "pos_hg38": 123773274, "p": 3.87554e-26,
        "snp_level_auto": "known", "locus_level_auto": "known", "combined_auto": "known",
        "evidence_summary": {"n_studies": 1, "n_ancestries": 1, "ancestry_set": ["European"],
                             "max_n": 141355, "year_range": [2021, 2021], "has_replication": False},
        "prior_reports": [{"catalog_lead": "rs3945628", "r2": 1.0, "efo_match_type": "exact"}],
        "evidence_level": None, "agent_judgment": None, "user_confirmed": None,
    }]
    write_outputs(candidates, tmp_path, commands=["locus_novelty.py --loci x.csv"])
    assert (tmp_path / "candidates.json").exists()
    csv_text = (tmp_path / "draft_verdict.csv").read_text()
    assert "evidence_level" in csv_text.splitlines()[0]   # header has the column
    assert (tmp_path / "reproducibility" / "commands.sh").exists()
    assert "locus_novelty.py --loci x.csv" in (tmp_path / "reproducibility" / "commands.sh").read_text()
