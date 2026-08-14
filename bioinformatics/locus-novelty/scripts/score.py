# bioinformatics/locus-novelty/scripts/score.py
"""Pure two-level novelty rules. No HTTP — operates on already-fetched prior_reports."""
from __future__ import annotations

SAME_SIMILAR = {"exact", "parent", "child"}


def snp_level_verdict(prior_reports: list[dict], r2_threshold: float = 0.2) -> str:
    same = [p for p in prior_reports if p.get("efo_match_type") in SAME_SIMILAR]
    diff = [p for p in prior_reports if p.get("efo_match_type") == "none"]
    max_same = max((p["r2"] for p in same if p.get("r2") is not None), default=None)
    max_diff = max((p["r2"] for p in diff if p.get("r2") is not None), default=None)
    if max_same is not None and max_same >= r2_threshold:
        return "known"
    if max_diff is not None and max_diff >= r2_threshold:
        return "shared_signal_different_trait"
    return "novel_signal"


def locus_level_verdict(prior_reports: list[dict]) -> str:
    # priors are already window-filtered (±locus_window) by the CLI
    if any(p.get("efo_match_type") in SAME_SIMILAR for p in prior_reports):
        return "known"
    return "novel_locus"


def combine(snp_level: str, locus_level: str) -> str:
    if snp_level == "known" and locus_level == "known":
        return "known"
    if snp_level == "novel_signal" and locus_level == "known":
        return "novel_signal_on_known_locus"
    if snp_level == "novel_signal" and locus_level == "novel_locus":
        return "novel_locus_and_signal"
    if snp_level == "shared_signal_different_trait":
        return f"shared_signal_different_trait/{locus_level}"
    return f"{snp_level}/{locus_level}"


def evidence_descriptors(prior_reports: list[dict]) -> dict:
    """Objective summaries of the supporting-study evidence — NOT a verdict.

    The agent reads these + the abstracts and assigns the evidence verdict;
    rigid thresholds mislead (same-biobank studies aren't independent, etc.).
    Studies are deduped by accession (one study reporting several associations
    at the locus counts once), but all ancestry facts are aggregated.
    """
    studies: set[str] = set()
    ancestries: set[str] = set()
    max_n = 0
    years: list[int] = []
    has_replication = False
    for p in prior_reports:
        s = p.get("study") or {}
        acc = s.get("accession")
        if acc:
            studies.add(acc)
        for anc in (s.get("ancestries") or []):
            if anc.get("type") == "replication":
                has_replication = True
            for g in (anc.get("ancestral_groups") or []):
                if g:
                    ancestries.add(g)
            n = anc.get("n")
            if isinstance(n, (int, float)) and n > max_n:
                max_n = int(n)
        y = s.get("year")
        if isinstance(y, int):
            years.append(y)
    return {
        "n_studies": len(studies),
        "n_ancestries": len(ancestries),
        "ancestry_set": sorted(ancestries),
        "max_n": max_n or None,
        "year_range": [min(years), max(years)] if years else None,
        "has_replication": has_replication,
    }
