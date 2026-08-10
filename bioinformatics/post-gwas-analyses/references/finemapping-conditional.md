# Fine-Mapping, Conditional Analysis, and Colocalization

Load when the user wants to identify causal variants within a significant locus (SuSiE), separate independent signals (GCTA-COJO), or test whether two traits share a causal variant (coloc).

## Table of contents

- [Workflow overview](#workflow-overview)
- [Fine-mapping with SuSiE](#fine-mapping-with-susie)
- [Conditional analysis with GCTA-COJO](#conditional-analysis-with-gcta-cojo)
- [Colocalization with coloc](#colocalization-with-coloc)

## Workflow overview

All three methods work within a **locus**: define the region (lead variant ± 500 kb or 1 Mb), compute the LD matrix from a reference panel matched to cohort ancestry, and interrogate the sumstats in that window. The lead variant comes from clumping or `gwaslab`'s ld_block/find_lead utilities (see PRS reference for clumping flags).

The three answer different questions — run the relevant one, not all three:

| Method | Question | Input |
|--------|----------|-------|
| SuSiE fine-mapping | which variant(s) are likely causal? | sumstats + LD (R) matrix |
| COJO conditional | how many independent signals in the locus? | sumstats + LD (bim/bfile) |
| coloc | do two traits share the causal variant? | two traits' sumstats + LD |

## Fine-mapping with SuSiE

Bayesian model: each locus is a sum of L sparse "single effects" (L = max number of causal variants, default 10). Output: per-variant **PIP** (posterior inclusion probability — probability variant j is causal) and **credible sets** (minimal variant sets with probability ≥ α of containing the causal variant; α = 0.95 standard).

```bash
# 1. Extract the locus sumstats + SNP list
# 2. Compute the LD (r) matrix from a reference panel
plink --bfile reference_eas \
    --keep-allele-order \
    --r square \
    --extract sig_locus.snplist \
    --out sig_locus_ld
```

```r
# 3. SuSiE-RSS: fine-mapping from summary statistics
library(susieR)
# bhat = effect sizes, shat = SEs, R = LD matrix, n = sample size
fit <- susie_rss(bhat, shat, R, n = n, L = 10)
# -> fit$pip (per-variant PIP), fit$sets$cs (credible sets)
```

- **PIP > 0.5** is a strong candidate; a 95% credible set containing a few variants means the data cannot distinguish them — report the whole set, not just the top variant.
- If the credible set is huge (>50 variants), the locus lacks resolution (LD too high, N too low) — say so; "the most likely variant is rs123" alone would overstate the evidence.
- SuSiE-RSS assumes one causal signal per locus per L; rerun with the locus trimmed if the lead variant sits on a recombination boundary.
- Coloc and fine-mapping are complementary: fine-mapping within one trait, coloc across two.

## Conditional analysis with GCTA-COJO

Separates independent association signals by conditioning: the lead variant becomes a covariate, and residual signal is tested. Stepwise model selection (`--cojo-slct`) reports the number of independent SNPs.

```bash
# 1. Prepare sumstats in COJO format: SNP, A1, A2, freq, b, se, p, N
# 2. Run stepwise selection (needs an LD reference bfile of the right ancestry)
gcta --bfile reference_eas \
    --cojo-file sumstats.cojo \
    --cojo-slct \
    --cojo-wind 10000 \
    --extract-region-bp <chr> <start> <end> \
    --out locus
```

- `--cojo-wind 10000` = 10 kb window for LD-based independence; typical choice.
- Output: one line per independent signal (SNP, P, conditional P). Multiple signals in a locus → each is a candidate for separate fine-mapping/colocalization.
- Requires > 4000 unrelated reference samples for stable LD; report the reference used.
- COJO tells you *how many* signals; SuSiE tells you *which variants* plausibly cause each.

## Colocalization with coloc

Tests five hypotheses for two traits in one region: H0 neither associated, H1 only trait 1, H2 only trait 2, H3 both but different causal variants, H4 both sharing the same causal variant. Output: posterior probabilities PP.H0–PP.H4.

```r
library(coloc)
# coloc.abf needs: beta/se (or p), MAF, type, N per variant for each trait
res <- coloc.abf(dataset1, dataset2)
# PP.H4 > 0.8 is commonly treated as strong evidence of sharing
```

- **PP.H4 > 0.8** is the common threshold for claiming a shared causal variant; report PP.H3 (different variants) alongside — high H3 + low H4 means the traits co-associate but through distinct variants, which is itself a useful finding.
- The single-causal-variant assumption of `coloc.abf` is a real limitation in complex loci — SuSiE-Coloc handles multiple causal variants per trait; recommend it when the locus has >1 signal.
- coloc needs per-variant MAF in both datasets (approximations acceptable: use reference-panel MAF or the study EAF) — with different MAF definitions, sensitivities shift; state which you used.
- A coloc result is per-locus, not genome-wide: choose the region *before* running (e.g. a credible set, or ±500 kb of a lead), and say whether the choice was hypothesis-driven or data-driven.
