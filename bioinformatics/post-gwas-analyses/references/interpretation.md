# Interpretation: Winner's Curse, Bias, and Result Reporting

Load when the user wants to interpret GWAS results, correct effect sizes, or write up findings — the statistical genetics that governs what a GWAS result *means*.

## Table of contents

- [Winner's curse](#winners-curse)
- [Bias taxonomy](#bias-taxonomy)
- [Reporting checklist](#reporting-checklist)

## Winner's curse

GWAS hits are selected on P-value — and P-value selection overestimates effect sizes. Conditional on passing a threshold, the observed β is biased upward (in absolute value); the smaller the discovery sample, the worse the bias.

- **When it applies:** any effect size reported from a significance-filtered scan (the reported OR/β of a "hit"), and any downstream use that trusts those numbers (PRS built from them, replication planning).
- **When it does not:** effect estimates from truly independent replication samples, and methods designed to be selection-aware.
- **Magnitude:** worst for small samples and stringent thresholds; can inflate OR by tens of percent in underpowered studies.

**Correction:** with only the significant variants' β and SE, solve the selection-conditional mean equation — E[β_obs | selected, β_true] = β_true + σ·[φ(z−c) − φ(−z−c)]/[Φ(z−c) + Φ(−z−c)] — for β_true numerically (root-finding, e.g. Brent's method; R package `winnerscurse`, or scipy's `brentq`). Direction: this only corrects the magnitude, not the direction.

Practical stance: for discovery reporting, report raw estimates and note the bias direction; for PRS construction, prefer methods robust to winner's curse (validation-based thresholding, shrinkage) over naive scores (see PRS reference); for replication power calculations, use corrected effects.

## Bias taxonomy

Four families explain most "wrong" GWAS conclusions; check them before trusting any finding:

1. **Confounding** — population stratification, cryptic relatedness, assortative mating. Symptom: inflated λ_GC / QQ deviation. Remedy: PCs, LMM, family-based designs.
2. **Measurement/information bias** — phenotype misclassification (e.g. self-reported cases), batch effects, differential genotyping error. Symptom: effect-size attenuation (non-differential) or spurious signal (differential).
3. **Selection bias** — collider bias (adjusting for a collider opens a backdoor path), participation/ascertainment bias (health-conscious volunteers), case-control ascertainment distorting effect sizes.
4. **Analysis-induced bias** — model misspecification, multiple testing without control, winner's curse (above), P-hacking.

A useful habit: for any surprising result, ask which of the four could produce it without changing the conclusion — if one plausibly does, the result needs a robustness check, not a press release.

## Reporting checklist

For any GWAS deliverable (report, figure, methods paragraph):

- Study design: case-control vs cohort, ancestry, genotyping platform, imputation panel (and Rsq threshold), sample sizes per phenotype.
- QC: variant/sample filters (MAF, missingness, HWE, relatedness cutoff) with counts removed at each step.
- Model: regression type, covariates (which PCs), software + version, Firth/SPA use.
- Results: effect allele, effect size (β or OR), SE, P, per-variant N; λ_GC or LDSC intercept for inflation; number of independent loci and how they were defined (clumping parameters).
- Corrections: multiple-testing procedure, and for post-GWAS analyses the LD reference, window, and per-method thresholds (PP.H4, PIP/credible sets, p_HEIDI, F-statistics, etc.).
- Limitations: what the study cannot say (causality without MR/follow-up; portability across ancestries; winner's curse in effect sizes).
