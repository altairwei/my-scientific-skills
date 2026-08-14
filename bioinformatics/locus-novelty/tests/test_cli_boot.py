# bioinformatics/locus-novelty/tests/test_cli_boot.py
def test_cli_imports_cleanly():
    import locus_novelty
    assert hasattr(locus_novelty, "run_pipeline")
    assert hasattr(locus_novelty, "main")


def test_attach_abstracts_fills_study_abstract_and_skips_pmidless(monkeypatch):
    import locus_novelty
    monkeypatch.setattr(locus_novelty.pubmed, "abstracts",
                        lambda pmids, client=None: {"111": "We studied PCOS."} if "111" in pmids else {})
    priors = [
        {"catalog_lead": "rs1", "r2": 1.0, "efo_match_type": "exact",
         "study": {"accession": "GCST1", "pmid": "111", "abstract": None}},
        {"catalog_lead": "rs2", "r2": 0.1, "efo_match_type": "none",
         "study": {"accession": "GCST2", "pmid": "222", "abstract": None}},   # 222 not returned -> ""
        {"catalog_lead": "rs3", "r2": 0.0, "efo_match_type": "exact", "study": {}},  # no pmid -> skipped
    ]
    out = locus_novelty._attach_abstracts(priors, client=object())
    assert out[0]["study"]["abstract"] == "We studied PCOS."
    assert out[1]["study"]["abstract"] == ""
    assert "abstract" not in out[2]["study"]   # untouched (no pmid)
