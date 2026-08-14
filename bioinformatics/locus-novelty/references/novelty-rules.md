# locus-novelty rules

## Three levels

**SNP level (signal level):** for each study lead SNP, compute LD r² against
each cataloged lead SNP of prior associations at the locus (from GWAS Catalog
`/singleNucleotidePolymorphisms/{rsid}/associations` + the ±`--locus-window`
region query). The "cataloged lead SNP" is the `riskAlleleName` minus the
allele suffix (e.g. `rs3945628-C` → `rs3945628`).

- max r² ≥ threshold **and** same/similar phenotype (EFO exact/parent/child) →
  `known` (same signal).
- r² < threshold against all same-phenotype cataloged leads → `novel_signal`.
- r² ≥ threshold **only** with different-phenotype priors →
  `shared_signal_different_trait` (the variant is known for another trait).

**Locus level:** any prior association with a same/similar phenotype within
±`--locus-window` → `known`; none → `novel_locus`. Independent of LD — a novel
signal can sit on a known locus (different haplotype, same region).

**Evidence-base level (agent-judged, no auto-score):** for a known/likely-known
locus, the agent reviews the supporting studies the CLI captured — each prior
association's study (accession, PMID, author, year, journal, sample N,
ancestries) + PubMed abstract + the `evidence_summary` descriptors
(`n_studies`, `n_ancestries`, `ancestry_set`, `max_n`, `year_range`,
`has_replication`) — and judges the strength/breadth of the evidence base.

- `well_replicated` — multiple independent studies/cohorts, ideally across
  ancestries, adequate N, consistent direction.
- `single_study` — only one study reports it.
- `limited_evidence` — few/small studies, single ancestry, unreplicated, or
  inconsistent.
- `n/a` — locus is novel (no priors to assess).

**Why this level is not auto-scored:** evidence strength resists rigid rules.
Two studies from the same biobank/consortium are not independent; large N but a
single ancestry raises generalizability doubt; an old unreplicated signal is
stale; a recent meta-analysis can supersede earlier reports. The CLI computes
only objective *descriptors* (counts, ranges) — never a verdict — so the agent
reads them alongside the abstracts and judges. Studies are deduped by accession
(one study reporting several associations at the locus counts once), but all
ancestry facts are aggregated. Unpublished catalog entries (no PMID) still count
as evidence — they get no abstract.

## Combined verdicts

SNP and locus levels combine (CLI auto-scored); the evidence level is reported
alongside, agent-assigned. The evidence level modulates only when the locus is
known (priors exist); a `novel_locus_and_signal` locus has evidence `n/a`.

| SNP level | Locus level | Combined (auto) | Evidence (agent) |
|---|---|---|---|
| known | known | `known` | well_replicated / single_study / limited_evidence |
| novel_signal | known | `novel_signal_on_known_locus` | (assess the known locus's studies) |
| novel_signal | novel_locus | `novel_locus_and_signal` | n/a |
| shared_signal_different_trait | (any) | `shared_signal_different_trait/{locus}` | (assess) |

## Edge cases

- **EFO unresolved** (trait not in EFO / OLS lookup fails): `efo_match_type =
  None`; the CLI cannot auto-score, so the locus is flagged `efo_unresolved`
  and **all** candidate priors are surfaced for the agent/user to judge
  manually. Never auto-declare novel on an unresolved EFO.
- **rsID not in Ensembl**: resolve fails → locus skipped with `status=resolve_failed`; report it.
- **No prior associations in the locus**: `novel_locus` + `novel_signal` + evidence `n/a` (no priors to LD against or read).
- **Multi-allelic / indel lead SNPs**: LDlink and PLINK handle standard rsIDs; non-SNV leads are skipped with a warning (r² undefined for complex variants in this pipeline).
- **Study with no PMID** (unpublished catalog entry): no abstract fetched; still counts toward `n_studies`/`evidence_level`.

## COJO complementarity

GCTA-COJO (`post-gwas-analyses`, GWASTutorial `18_Conditioning_analysis`) is the
**statistical** angle: it conditions on a known signal using your own sumstats +
an LD reference, answering "is this signal independent given my data?". This
skill is the **bibliographic** angle: it asks "is this signal already in the
published literature (GWAS Catalog), for a same/similar phenotype, and how
well-supported?". They can agree (statistically independent AND unreported →
strong novel candidate) or diverge (statistically independent but already
reported for a different trait → `shared-signal-different-trait`). Run both when
the novelty verdict matters.
