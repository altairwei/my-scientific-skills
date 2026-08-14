# bioinformatics/locus-novelty/tests/test_score.py
from score import snp_level_verdict, locus_level_verdict, combine, evidence_descriptors


def _prior(lead, r2, efo):
    return {"catalog_lead": lead, "r2": r2, "efo_match_type": efo}


def test_snp_known_when_same_phenotype_r2_above_threshold():
    priors = [_prior("rs999", 0.95, "exact"), _prior("rs888", 0.1, "exact")]
    assert snp_level_verdict(priors, r2_threshold=0.2) == "known"


def test_snp_novel_when_all_same_phenotype_below_threshold():
    priors = [_prior("rs999", 0.1, "parent"), _prior("rs888", 0.05, "exact")]
    assert snp_level_verdict(priors, r2_threshold=0.2) == "novel_signal"


def test_snp_shared_signal_different_trait_when_high_r2_only_with_different_phenotype():
    priors = [_prior("rs999", 0.9, "none"), _prior("rs888", 0.1, "exact")]
    assert snp_level_verdict(priors, r2_threshold=0.2) == "shared_signal_different_trait"


def test_locus_known_when_any_same_phenotype_prior_in_window():
    priors = [_prior("rs999", 0.0, "exact")]   # r2 irrelevant for locus level
    assert locus_level_verdict(priors) == "known"


def test_locus_novel_when_no_same_phenotype_prior():
    priors = [_prior("rs999", 0.9, "none")]
    assert locus_level_verdict(priors) == "novel_locus"


def test_combine_novel_signal_on_known_locus():
    c = combine(snp_level="novel_signal", locus_level="known")
    assert c == "novel_signal_on_known_locus"


def test_combine_fully_novel():
    assert combine("novel_signal", "novel_locus") == "novel_locus_and_signal"


def test_combine_known_signal_known_locus():
    assert combine("known", "known") == "known"


def _prior_with_study(lead, study):
    return {"catalog_lead": lead, "r2": 0.0, "efo_match_type": "exact", "study": study}


def test_evidence_descriptors_dedups_studies_and_aggregates_ancestry():
    priors = [
        _prior_with_study("rs1", {"accession": "GCST1", "year": 2021,
            "ancestries": [{"type": "initial", "n": 141355,
                            "ancestral_groups": ["European"], "country": ["Finland"]}]}),
        _prior_with_study("rs2", {"accession": "GCST1", "year": 2021,   # same study, 2nd association -> dedup count
            "ancestries": [{"type": "replication", "n": 233398,
                            "ancestral_groups": ["European"], "country": ["Estonia"]}]}),
        _prior_with_study("rs3", {"accession": "GCST2", "year": 2015,
            "ancestries": [{"type": "initial", "n": 20000,
                            "ancestral_groups": ["East Asian"], "country": ["Japan"]}]}),
    ]
    d = evidence_descriptors(priors)
    assert d["n_studies"] == 2                  # GCST1 reported twice -> counts once
    assert d["n_ancestries"] == 2              # European, East Asian
    assert d["ancestry_set"] == ["East Asian", "European"]   # sorted
    assert d["max_n"] == 233398
    assert d["year_range"] == [2015, 2021]
    assert d["has_replication"] is True


def test_evidence_descriptors_empty_when_no_studies():
    assert evidence_descriptors([]) == {
        "n_studies": 0, "n_ancestries": 0, "ancestry_set": [],
        "max_n": None, "year_range": None, "has_replication": False}
