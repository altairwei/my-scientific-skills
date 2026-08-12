# locus-novelty rules

## Two levels

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

## Combined verdicts

| SNP level | Locus level | Combined |
|---|---|---|
| known | known | `known` |
| novel_signal | known | `novel_signal_on_known_locus` |
| novel_signal | novel_locus | `novel_locus_and_signal` |
| shared_signal_different_trait | (any) | `shared_signal_different_trait/{locus}` |

## Edge cases

- **EFO unresolved** (trait not in EFO / OLS lookup fails): `efo_match_type =
  None`; the CLI cannot auto-score, so the locus is flagged `efo_unresolved`
  and **all** candidate priors are surfaced for the agent/user to judge
  manually. Never auto-declare novel on an unresolved EFO.
- **rsID not in Ensembl**: resolve fails → locus skipped with `status=resolve_failed`; report it.
- **No prior associations in the locus**: `novel_locus` + `novel_signal` (no priors to LD against).
- **Multi-allelic / indel lead SNPs**: LDlink and PLINK handle standard rsIDs; non-SNV leads are skipped with a warning (r² undefined for complex variants in this pipeline).

## COJO complementarity

GCTA-COJO (`post-gwas-analyses`, GWASTutorial `18_Conditioning_analysis`) is the
**statistical** angle: it conditions on a known signal using your own sumstats +
an LD reference, answering "is this signal independent given my data?". This
skill is the **bibliographic** angle: it asks "is this signal already in the
published literature (GWAS Catalog), for a same/similar phenotype?". They can
agree (statistically independent AND unreported → strong novel candidate) or
diverge (statistically independent but already reported for a different trait →
`shared-signal-different-trait`). Run both when the novelty verdict matters.
