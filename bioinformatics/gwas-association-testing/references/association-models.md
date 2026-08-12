# Association Testing Models & Interpretation

Load when running the association test itself, choosing the model, checking result quality (genomic control), visualizing results, or explaining effect sizes and significance.

## Table of contents

- [Genetic models](#genetic-models)
- [Regression models](#regression-models)
- [PLINK 2 association commands](#plink-2-association-commands)
- [Result QC: genomic control](#result-qc-genomic-control)
- [Multiple testing and significance](#multiple-testing-and-significance)
- [Visualization](#visualization)
- [Phenotype preparation](#phenotype-preparation)
- [Effect measures](#effect-measures)
- [Statistical power](#statistical-power)

## Genetic models

For a biallelic SNP with reference allele A and alternative G, genotypes AA/AG/GG are encoded per model:

| Model | AA | AG | GG |
|-------|----|----|----|
| Additive (ADD) | 0 | 1 | 2 |
| Dominant (DOM) | 0 | 1 | 1 |
| Recessive (REC) | 0 | 0 | 1 |

- **Additive** is the default: each copy of the effect allele changes the trait by β. Most complex-trait signal is approximately additive.
- **Dominant/recessive** are alternatives when the trait response is not linear in allele count; testing them costs a second test per variant — mention the multiple-testing cost to the user if they ask for all three.
- Chi-square tests (2×2 table for DOM/REC, Cochran–Armitage trend for ADD) work but cannot adjust for covariates — use regression when any covariate matters.

## Regression models

**Quantitative trait — linear regression:**
y = G·β_G + X·β_X + e
β_G is the per-allele effect on the phenotype. Adding covariates X (age, sex, PCs) removes their confounding.

**Binary trait — logistic regression:**
logit(p) = G·β_G + X·β_X
The effect is an odds ratio (OR) per allele copy. With common variants and balanced case/control the standard fit is fine; with rare variants or unbalanced designs the maximum-likelihood estimate is biased — use **Firth penalized regression** (adds a penalty term to the log-likelihood to shrink the estimate toward unbiasedness).

**Why PCs as covariates:** population stratification correlates allele frequency with phenotype through ancestry, not causality. Including the top PCs as covariates conditions on ancestry; the residual association is then interpretable as genetic.

**Relatedness:** standard regression assumes unrelated samples. With relatives, effect estimates stay unbiased but standard errors (and hence P values) are wrong — that is the textbook reason to either restrict to unrelated samples (KING cutoff 0.0884) or use LMM/REGENIE/SAIGE (see advanced-methods).

## PLINK 2 association commands

```bash
# Binary trait, logistic regression with Firth correction (tutorial workflow):
plink2 \
    --bfile sample_data.clean \
    --pheno pheno.txt --pheno-name B1 \
    --covar pca_projected.sscore --covar-col-nums 6-10 \
    --maf 0.01 \
    --glm hide-covar firth firth-residualize single-prec-cc \
    --out gwas
```

- `--glm` runs logistic (binary) or linear (quantitative) regression per variant, additive by default; `--glm dominant` / `--glm recessive` for the other models.
- `firth firth-residualize single-prec-cc` is required by current PLINK 2 releases for Firth (algorithm and precision changed in 2023). `firth-fallback` runs common variants without Firth for speed and uses Firth only where the standard fit fails.
- `hide-covar` keeps the per-variant output file free of covariate rows.
- **Effect allele:** PLINK 2 reports A1 = effect allele in the sumstats; `omit-ref` forces ALT == A1 so the effect refers to the alternative allele, which makes merging with other datasets unambiguous.
- `cols=+a1freq,+machr2` adds allele-1 frequency and imputation quality columns — ask for them when the results may be meta-analyzed or shared.
- `--covar-variance-standardize` normalizes covariates with huge scales (e.g. age²).

```bash
# Typical production invocation:
plink2 --bfile sample_data.clean \
    --keep unrelated.sample.id \
    --pheno pheno.txt --pheno-name B1 \
    --covar pca_projected.sscore --covar-col-nums 6-10 \
    --maf 0.01 --mach-r2-filter 0.7 2.0 \
    --glm cols=+a1freq,+machr2 firth-fallback omit-ref \
    --out gwas
```

**Output format:** one line per variant with #CHROM, POS, ID, REF, ALT, A1 (effect allele), A1_FREQ, TEST, OBS_CT, OR (or BETA), SE, Z_STAT, P, ERRCODE. Check `ERRCODE`: `FIRTH_CONVERGE_FAIL` rows have NA statistics — count and report them, don't silently drop.

**Verify from the log:** samples loaded (cases/controls), variants loaded and remaining after MAF filter, covariates loaded. Any of these wrong → stop and fix the input.

## Result QC: genomic control

λ_GC = median(observed χ²) / median(χ²₁) where median(χ²₁) ≈ 0.455.

- Compute it from your sumstats; **λ ≈ 1.0 expected**. If λ is clearly above 1, you have inflation — stratification, cryptic relatedness, or a misspecified model. Look at a QQ plot to see whether inflation is uniform (confounding) or confined to the top tail (real signal).
- Genomic control correction (dividing observed χ² by λ) is a crutch, not a fix — it assumes uniform inflation and is blind to genuine polygenic signal. Prefer fixing the model (PCs, LMM) over applying GC.
- For highly polygenic traits the "most variants are null" assumption breaks and λ is naturally > 1 even in a perfect analysis — interpret accordingly.

## Multiple testing and significance

- Testing ~1M effectively independent variants → Bonferroni: 0.05 / 10⁶ ≈ 5×10⁻⁸, the **genome-wide significance** threshold (derived from HapMap3 LD structure).
- P ∈ (10⁻⁵, 5×10⁻⁸) = **suggestive** — worth replication, not a finding.
- **FDR** (Benjamini–Hochberg) controls the expected fraction of false positives among the rejected tests; appropriate for exploratory screens (e.g. gene-level, QTL) rather than GWAS discovery.
- Reporting: always report effect allele, effect size, SE, P, and the model. Never report only "significant/non-significant."

## Visualization

Three canonical plots, all producible with `gwaslab` (Python):

| Plot | Needs | Reads out |
|------|-------|-----------|
| Manhattan | CHR, POS, P | genome-wide overview; -log10(P) vs position; threshold lines at 5×10⁻⁸ (and 10⁻⁵ suggestive) |
| QQ | P | observed vs expected P under U(0,1); deviation of the whole curve = inflation, top-tail deviation = signal |
| Regional | CHR, POS, P + LD r² with lead variant | a single locus: LD coloring shows which variants share the signal |

**Use a mature plotting package — do not hand-roll Manhattan/QQ code.** Prefer [`gwaslab`](https://github.com/Cloufield/gwaslab) (Python), which handles genome layout, chromosome coloring, threshold lines, and lead annotation correctly out of the box. When the user has only sumstats and needs plots fast, this is the default — install via `uv run --with gwaslab python -c "import gwaslab as gl; ..."` if the package is missing.

**Never write your own SNP downsampling.** A Manhattan plot must show every variant — the dense "haze" of null variants below the threshold line is the visual reference against which the signal peaks are read. Naive downsampling (e.g. "sample 10% of −log10(P) < 3 points to speed up the plot") carves a visible density cliff into that haze, producing an ugly banded plot and misleading the reader about how many variants were tested. This is a common failure mode when an agent reaches for matplotlib directly on a million-row sumstats file. The industry default is **no downsampling at all** — plot every point. The performance problem this mistake is trying to solve is real (vector PDFs with 10⁶+ points balloon to gigabytes), but the correct fix is **rasterization**, not subsampling: render the haze layer as a raster (PNG) backend or with `rasterized=True` on the scatter artist, keep only the annotation/highlight elements as vector. `gwaslab` already does this; a hand-rolled matplotlib path should set `rasterized=True` on the main scatter and export to a raster format (`.png`) or a mixed PDF. If you ever feel the urge to downsample for speed, stop — rasterize instead.

Lead-variant extraction: `gwaslab`'s `ld_block` / `find_lead` utilities cluster significant variants within LD windows and report the top hit per locus; alternatively `plink --clump` (see post-gwas-analyses PRS reference for clumping flags).

**Standard format for sharing:** GWAS-SSF (tab-separated data file + metadata file) — now the GWAS Catalog standard. If the user wants to deposit or exchange sumstats, offer to convert.

## Phenotype preparation

Raw phenotypes need QC before testing:

- **Outlier/range validation** first (implausible values are usually coding errors).
- **Quantitative traits** — normalize:
  - Well-behaved (roughly normal): regress on covariates (age, sex, medication), then Z-score the residuals.
  - Skewed: rank-based **inverse normal transformation** — INT = Φ⁻¹((r − c)/(n + 1 − 2c)) with Blom's c = 3/8 — applied to residuals. Robust to outliers, preserves rank order.
- **Binary traits**: use raw 0/1; do not transform.
- **Medication**: adjusting for treatment is complicated (indicator variable, dosage adjustment, pre-correction, or exclusion of treated); decide with the user based on what the study measures.

## Effect measures

- **Risk** = E/(E+N); **Odds** = E/N (event to non-event ratio).
- **Relative risk** RR = risk_exposed/risk_unexposed; **Odds ratio** OR = odds_exposed/odds_unexposed — from a 2×2 table OR = (IE·CN)/(CE·IN). OR ≈ RR when the event is rare (<10%).
- **Hazard ratio** HR = exp((X_i − X_j)β) from a Cox proportional hazards model — time-to-event data.
- In sumstats, β/SE (quantitative) and OR (binary) are the effect measures; converting OR→β (log OR) is standard for meta-analysis.

## Statistical power

Power = Pr(reject | true effect). For a quantitative trait the non-centrality parameter is NCP = N · 2f(1−f)β² / Var(y); power rises with sample size N, effect size β, allele frequency f (up to 0.5), and falls with stricter significance thresholds. Case-control power depends on N_cases · N_controls / (N_cases + N_controls) — balanced designs are most efficient.

Advise the user: a power calculation before genotyping (web tools: GAS Power Calculator) is cheap insurance; after data collection it only tells you what your study cannot detect. Doubling significance stringency costs roughly a 2× sample size for the same power.
