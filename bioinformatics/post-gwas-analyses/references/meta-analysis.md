# GWAS Meta-Analysis

Load when the user wants to combine their study with other cohorts' summary statistics to increase power, or to quantify between-study heterogeneity.

## Table of contents

- [When to meta-analyze](#when-to-meta-analyze)
- [Workflow](#workflow)
- [Methods](#methods)
- [Reference commands](#reference-commands)

## When to meta-analyze

Meta-analysis is worthwhile when the component studies (a) test the same phenotype, (b) are harmonizable at the allele/strand/build level, and (c) have non-overlapping samples. Overlapping samples make results anti-conservative (doubly counted evidence) — if cohorts share participants, prefer LDSC-style methods or report the overlap explicitly.

## Workflow

1. **Harmonize** all studies to one canonical format first (see sumstats-basics): same allele coding, same effect direction (flip β and EAF when A1 differs), same build, palindromic SNPs resolved (frequency-based or dropped — report how many).
2. **QC each study**: remove MAF outliers per study (a variant common in one and absent in another is usually a strand/allele error), multiallelic and duplicated variants, and variants failing imputation-quality filters.
3. **Choose the model** (fixed vs random — below).
4. **Run** (METAL for the classic pipeline; MR-MEGA for cross-ancestry).
5. **Report heterogeneity** (Q, I²) per locus alongside the combined estimate.

## Methods

- **Fixed-effects (inverse-variance weighted, IVW):** β_bar = Σ(w_k·β_k)/Σ(w_k) with w_k = 1/Var(β_k). Assumes one true effect across studies — appropriate for same-phenotype, same-ancestry replication studies.
- **Random-effects (DerSimonian–Laird):** adds between-study variance τ² to the weights; appropriate when studies genuinely differ (phenotype definition, ancestry, environment). More conservative; use when I² is high and the heterogeneity is real rather than technical.
- **Sample-size-based approach:** when SEs are unavailable, weights proportional to N; less efficient, no heterogeneity metrics.
- **Cross-ancestry:** MR-MEGA meta-regression along MDS axes of ancestry (estimates trans-ancestry effects); MANTRA (Bayesian) for very heterogeneous sets.
- **Rare variants:** combine score statistics instead of effect sizes: S* = Σ S_k, V* = Σ V_k (RAREMETAL/Meta-SAIGE/MetaSKAT family) — single-variant meta is underpowered for rare alleles.

## Reference commands

```bash
# METAL: fixed-effects, per-study files with SNP, A1, A2, freq, beta, se, p, N
metal << EOF
SCHEME STDERR
SEPARATOR TAB
MARKER SNP
ALLELE A1 A2
EFFECT BETA
STDERR SE
PVALUE P
FREQ EAF
WEIGHT N
PROCESS study1.txt
PROCESS study2.txt
ANALYZE HETEROGENEITY
OUTFILE meta_result .txt
EOF
```

- `ANALYZE HETEROGENEITY` outputs Cochran's Q and I² = (Q − df)/Q·100% per variant — report these; a hit with I² > 75% needs explanation before being called "the" meta-effect.
- Check METAL's allele-flip log carefully: it flips effects when A1/A2 are swapped and warns on palindromic mismatches — read those warnings.

Interpretation: a meta-analysis combines evidence, it does not create it. A genome-wide hit that appears only in meta (not in any single study) is plausible — that is the point — but still needs replication in an independent cohort. Report per-study N and ancestry along with the combined result.
