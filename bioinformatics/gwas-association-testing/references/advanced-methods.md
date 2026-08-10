# Advanced Association Methods: LMM, REGENIE, SAIGE, Rare Variants

Load when the cohort has related samples, complex ancestry, imbalanced case-control ratios, rare variants, or biobank scale — situations where standard regression is wrong or too slow.

## Table of contents

- [Choosing among models](#choosing-among-models)
- [Linear mixed models (concept)](#linear-mixed-models-concept)
- [REGENIE](#regenie)
- [SAIGE](#saige)
- [Rare-variant set tests](#rare-variant-set-tests)
- [Nonlinear effects](#nonlinear-effects)

## Choosing among models

| Situation | Model |
|-----------|-------|
| Unrelated, homogeneous samples | PLINK `--glm` (association-models reference) |
| Related samples / cryptic relatedness / complex ancestry | LMM (BOLT-LMM), REGENIE, SAIGE |
| Biobank scale (10⁵–10⁶ samples, many phenotypes) | REGENIE (fast, memory-efficient) |
| Imbalanced binary trait (e.g. 1:10–1:100 case:control) | SAIGE (or PLINK + Firth for common variants) |
| Rare variants | Set-based tests (burden/SKAT family) |
| Very large sample sizes (UKB-scale) | REGENIE or SAIGE with sparse GRM |

Model choice is a study-design decision made *before* looking at results — not a way to rescue inflated findings.

## Linear mixed models (concept)

y = Xβ + Zu + e, with u ~ N(0, σ²_g·K), Var(y) = A·σ²_g + I·σ²_e

- The random effect u with kinship/GRM covariance K absorbs population structure **and** relatedness simultaneously — that is why LMM "fixes" both problems at once.
- The tested variant is a fixed effect; the GRM term is estimated once and the test adjusted accordingly (this is what makes genome-wide LMM feasible — BOLT-LMM, REGENIE, SAIGE all exploit this factorization).
- Cost: GRM construction + REML is heavy; REGENIE and SAIGE avoid the full GRM (see below).

## REGENIE

Whole-genome regression: **two-step**, no GRM needed. Memory-efficient at biobank scale, handles binary + quantitative + survival traits, and its step-2 output doubles as input for gene-based tests.

**Step 1 — fit the polygenic model** on LD-pruned SNPs:
```bash
regenie \
  --step 1 \
  --bed sample_data.clean --extract pca_prune.prune.in \
  --phenoFile pheno.txt \
  --covarFile pca_projected.sscore --covarColList PC1_AVG,...,PC10_AVG \
  --bt --bsize 1000 --lowmem --lowmem-prefix tmpdir/tmp_preds \
  --out step1
```
- `--bt` = binary trait; omit for quantitative.
- Stacked ridge regression (Level 0: within-block predictors with multiple shrinkage parameters; Level 1: combine blocks) → per-sample polygenic predictions.
- **LOCO** (leave-one-chromosome-out): predictions for testing chromosome k are computed without chromosome k, so the variant being tested is never part of its own covariate. Keep `--loocv`/default LOCO behavior — never disable it for association testing.

**Step 2 — single-variant tests adjusted by the predictions:**
```bash
regenie \
  --step 2 \
  --bed sample_data.clean --ref-first \
  --phenoFile pheno.txt \
  --covarFile pca_projected.sscore --covarColList PC1_AVG,...,PC10_AVG \
  --bt --bsize 400 \
  --firth --approx --pThresh 0.01 \
  --pred step1_pred.list \
  --out step2
```
- `--ref-first`: REF is the effect allele (use ALT as effect with `--a1-freq` conventions consistently).
- `--firth --approx --pThresh 0.01`: Firth correction for variants with P < 0.01 (unbalanced designs).
- Step 2 can also output set-based tests (`--set-list`, `--aaf-file`, `--vc-tests` for burden/SKAT/etc.), GxE tests (`--interaction`), and Cox PH for survival traits (`--cox`).

**Output:** `step2_*.regenie` per phenotype: CHROM, POS, ID, ALLELE0, ALLELE1 (effect), A1FREQ, INFO, N, TEST, BETA, SE, CHISQ, LOG10P, EXTRA. Verify N and INFO look sane before interpreting.

## SAIGE

For **imbalanced case-control** (up to ~1:100): the normal approximation to the score statistic fails in the far tail for rare variants; SAIGE replaces it with **saddlepoint approximation (SPA)**, which is accurate to second order where normal approximation is only first order. The bias is real: standard logistic regression produces *inflated* (anti-conservative) P values for rare variants in imbalanced designs — SAIGE is the standard remedy in large biobank GWAS.

**Step 1 — fit the null GLMM** (GRM from LD-pruned SNPs, sparse GRM for big cohorts):
```bash
saige --fitNullGLMM \
  --plinkFile=sample_data.clean --sparseGRMFile=sparse.grm --sparseGRMSampleIDFile=sparse.sample \
  --phenoFile=pheno.txt --phenoCol=B1 --covarColList=PC1_AVG,...,PC10_AVG \
  --sampleFile=sample.id --traitType=binary --outputPrefix=saige_null
```
**Step 2 — per-variant tests** (parallelize by chromosome):
```bash
saige --vcf=chr1.vcf.gz --chrom=1 \
  --GMMATmodelFile=saige_null.rda --varianceRatioFile=saige_null.varianceRatio.txt \
  --sampleFile=sample.id --outputPrefix=chr1
```
- SAIGE-GENE/GENE+ extend to set-based (gene-level) tests.
- For common variants in balanced designs, SAIGE ≈ standard logistic regression — its cost is only justified by imbalanced designs or rare variants.

## Rare-variant set tests

Single-variant tests lack power below MAF ~0.001: you are testing one copy of an allele per hundreds of samples. Set tests aggregate variants within a unit (gene, region) and test the unit.

**Definitions:** ultra-rare MAF < 0.0001, rare < 0.001, low-frequency < 0.01 (some use < 0.05).

**Methods:**

- **Burden test:** collapses the set into a single score B = Σ w_j·G_ij, then tests B vs phenotype. Powerful when all variants affect the trait in the *same direction*; powerless when effects mix directions.
- **SKAT:** variance-component score test, powerful when effects have *mixed directions* (Q = (y−μ)′K(y−μ) with kernel weighting). Weights typically Beta(MAF; 1, 25) — upweighting rare variants.
- **SKAT-O:** adaptive combination of burden + SKAT (rho ∈ [0,1]) — the robust default when effect direction is unknown.
- **ACAT:** combines P values via a Cauchy transformation (T = Σ w_i·tan((0.5−p_i)π)) — no LD modeling needed, works on sumstats alone; ACAT-V adds variant weights.

**Workflow:** define variant sets (MAF threshold + functional annotation, e.g. loss-of-function, missense) → compute per-variant scores or sumstats → run set test → multiple-testing correction over genes. REGENIE step 2, SAIGE-GENE, MAGMA (post-GWAS reference), and R packages (SKAT, ACAT) all implement pieces of this.

## Nonlinear effects

- **Epistasis (G×G)** and **G×E** add interaction terms to the model. Genome-wide interaction scans are statistically brutal (~5×10¹¹ variant pairs) — the field tests *set-based* interactions (kernel methods: FastKAST, QuadKAST, MAPIT) or candidate-gene interactions instead.
- Marginal-epistasis tests (is the effect of focal variant i modified by the *rest* of the genome?) are more tractable than pairwise scans.
- Kernel choice matters: quadratic kernels capture pairwise interactions; RBF kernels capture broader nonlinearity. These methods are research-grade; for routine work, prefer single-variant G×E tests in REGENIE.
