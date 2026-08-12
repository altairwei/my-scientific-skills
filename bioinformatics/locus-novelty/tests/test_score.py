# bioinformatics/locus-novelty/tests/test_score.py
from score import snp_level_verdict, locus_level_verdict, combine


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
