# Mendelian Randomization, TWAS, and SMR

Load when the user wants causal inference from genetics: does an exposure cause an outcome (MR), which genes mediate trait risk through expression (TWAS/SMR).

## Table of contents

- [Mendelian randomization](#mendelian-randomization)
- [TWAS with FUSION](#twas-with-fusion)
- [SMR/HEIDI](#smrheidi)

## Mendelian randomization

MR uses genetic variants as **instrumental variables** for an exposure, inferring causality under three assumptions: (1) relevance — the instruments associate with the exposure; (2) exclusion restriction — instruments affect the outcome only through the exposure; (3) independence — instruments are not confounded with the outcome. Violations (especially horizontal pleiotropy) are the norm, not the exception — hence the mandatory sensitivity analyses.

**Workflow (TwoSampleMR + OpenGWAS):**

1. **Select instruments:** exposure variants with P < 5×10⁻⁸ (genome-wide), then clump to independence (`clump_data` with r² = 0.001–0.01 within 10 Mb) so each instrument is an independent locus.
2. **Check strength:** F-statistic for the exposure instruments (F > 10 conventionally acceptable; F < 10 instruments are weak and bias toward the null).
3. **Fetch/format outcome data** and **harmonize** exposure/outcome alleles (palindromic SNPs with ambiguous frequency — the harmonizer should drop or resolve; count them).
4. **Estimate:** Wald ratio per instrument, then combine — IVW (inverse-variance weighted) is the primary; **MR-Egger** (tests directional pleiotropy via its intercept), **weighted median** (robust to ≤50% invalid instruments), **simple/weighted mode**, and RAPS are sensitivity methods.
5. **Sensitivity:** Cochran's Q heterogeneity, MR-Egger intercept ≠ 0, leave-one-out (is one instrument driving the result?), Steiger directionality (is the causal direction actually exposure→outcome?). Report these, not just the headline estimate.

```r
library(TwoSampleMR)
exp <- extract_instruments("ieu-b-38")            # or own exposure sumstats
out <- extract_outcome_data(exp$SNP, "ieu-a-2")   # or own outcome sumstats
dat <- harmonise_data(exp, out)
res <- mr(dat, method_list = c("mr_ivw", "mr_egger_regression",
                               "mr_weighted_median", "mr_weighted_mode"))
mr_pleiotropy_test(dat); mr_heterogeneity(dat); mr_leaveoneout(dat)
```

- Two-sample MR (exposure and outcome from different studies) needs no overlapping samples; if samples overlap, inflation is possible.
- Report per-method estimates + sensitivity outputs together; a headline IVW with a significant Egger intercept is *conflicted*, not definitive.
- STROBE-MR checklist for reporting; and remember MR estimates are lifetime-exposure causal effects, not per-unit treatment effects — scale accordingly when the user compares with RCTs.

## TWAS with FUSION

TWAS imputes expression from genotype using eQTL weights (GTEx etc.), then tests the imputed expression against the trait: a gene whose *predicted* expression associates with the trait is prioritized. FUSION is the standard tool:

1. **Weights:** precomputed per-tissue expression weights (GTEx), or train with FUSION on expression+genotype data.
2. **Format sumstats** to LDSC style (SNP, A1, A2, Z — only variants in the LD reference).
3. Run per tissue/chromosome:

```bash
Rscript FUSION.assoc_test.R \
  --sumstats study.sumstats \
  --weights WEIGHTS/GTEx.<tissue>.pos \
  --ref_ld_chr ref_ld/ \
  --chr 1 --out twas_chr1
```

4. Correct for the number of genes tested (Bonferroni over genes).

Interpret honestly: TWAS significance means the gene's *cis-genetic component* of expression associates with the trait. Co-regulation (two genes sharing a cis-variant) and predicted-expression uncertainty produce false positives — treat TWAS as prioritization, confirm with colocalization (finemapping-conditional reference) and ideally experimental follow-up. Multiple tissues multiply testing — report the tissue list and correction.

## SMR/HEIDI

SMR (summary-data-based MR) treats variant→expression as the exposure and variant→trait as the outcome, estimating b_xy = b_zy / b_zx for the top cis-eQTL. **HEIDI** then tests whether the association is consistent across nearby SNPs (pleiotropy vs linkage): a passing HEIDI (p_HEIDI ≥ 0.05) supports one shared causal variant; a failing one points to two variants in LD (linkage) rather than a true shared causal mechanism.

```bash
# Inputs: GWAS sumstats (COJO format), xQTL BESD files, LD reference
smr --bfile ref_eas \
  --gwas-summary gwas.sumstats \
  --beqtl-summary eqtl.besd \
  --out smr_out
```

- Significance: p_SMR < 0.05/n_probes (Bonferroni over tested probes/genes) and `--peqtl-smr 5e-8` (only top eQTLs as instruments).
- Report both p_SMR and p_HEIDI: SMR+HEIDI-passing = good gene-prioritization evidence; SMR-passing but HEIDI-failing = likely LD artifact, do not claim a causal gene.
- SMR and coloc answer related questions with different machinery; when the user needs one, prefer coloc for shared-variant inference across two *phenotypes*, SMR for variant→expression→trait mediation.
