# Polygenic Risk Scores

Load when the user wants to build a genetic risk score from GWAS summary statistics, evaluate its predictive performance, or interpret a published PGS.

## Table of contents

- [Concept](#concept)
- [C+T workflow](#ct-workflow)
- [Reference commands](#reference-commands)
- [Validation](#validation)
- [Advanced methods and caveats](#advanced-methods-and-caveats)

## Concept

PRS = Σ x_ij · β_i: the individual's summed dosage of effect alleles weighted by their GWAS effect sizes. A PRS is only meaningful relative to a **population distribution** — report its variance explained (R²) or discriminative ability (AUC for binary traits), not raw scores.

The simplest robust approach is **C+T** (clumping + thresholding): clump SNPs for LD independence, then include variants by P-value threshold, choosing the threshold on a tuning/validation sample.

## C+T workflow

1. **Clump** the discovery sumstats against a reference panel (or the genotyping panel of the *target* cohort when available) so a locus contributes one representative SNP:
   - `--clump-p1 1` (or 0.0001 — include a range; see tutorial defaults below), `--clump-r2 0.1` (0.1–0.5), `--clump-kb 250`.
2. **Threshold** the clumped SNP set at several P values (0.001 … 0.5) — different traits have different optimal thresholds; don't guess, evaluate.
3. **Score** each threshold in the target cohort: PRS = Σ dosage · β.
4. **Select the threshold** by predictive performance in an independent validation sample (see below).
5. **Report** the final model's performance and the SNP count at the chosen threshold.

## Reference commands

```bash
# 1. Clump (discovery sumstats; SNP field + P field may need remapping)
plink --bfile target_or_ref \
  --clump sumstats.txt \
  --clump-p1 1 --clump-r2 0.1 --clump-kb 250 \
  --clump-snp-field SNPID --clump-field p.value \
  --out clumped
awk 'NR!=1 {print $3}' clumped.clumped > clumped.valid.snp

# 2. P-threshold ranges
printf "pT0.001 0 0.001\npT0.05 0 0.05\npT0.1 0 0.1\npT0.2 0 0.2\npT0.3 0 0.3\npT0.4 0 0.4\npT0.5 0 0.5\n" > range_list

# 3. Score the target cohort at every threshold (columns: SNP, A1, beta)
plink2 --bfile target_cohort \
  --score sumstats.tsv 1 2 3 header cols=nallele,scoreavgs,denom,scoresums \
  --q-score-range range_list SNP.pvalue \
  --extract clumped.valid.snp \
  --out prs
```

Always harmonize alleles (see sumstats-basics) before scoring: a flipped effect allele subtracts instead of adds. Check the fraction of variants matched between discovery and target — low overlap (different arrays, different builds) needs explanation before proceeding.

## Validation

- **PRS trained and evaluated on the same cohort is meaningless** — winner's curse inflates the performance. Split the cohort (train/discovery → tuning → validation) or use an external target sample; report performance **only** on data never used for threshold selection.
- Quantitative trait: R² of PRS in a regression of phenotype on PRS + covariates (age, sex, PCs); report the increment over covariates alone.
- Binary trait: AUC (ROC) and/or R² on the liability scale (Nagelkerke); report the case fraction.
- Sample size matters: an AUC of 0.6 from 100 cases is not the same story as from 10,000.
- If the user has no independent validation sample, say plainly that the score needs external validation before any clinical or research use — then offer the pseudo-validation/within-family options with their caveats.

## Advanced methods and caveats

- **LDpred, PRS-CS** — continuous shrinkage (Bayesian) priors on effect sizes; better than C+T when the trait is highly polygenic (many true effects below the P threshold). Need an LD reference; PRS-CS is a common modern default for European panels.
- **Meta-scoring / multi-trait PGS** — elastic net over per-trait PRS (e.g. PGS Catalog methods) when several related GWAS exist.
- **PGS Catalog** — published PGS models with standardized definitions; before building a new score, check whether a published PGS for the trait already performs adequately.
- Caveats to state in any report: portability of PRS across ancestries is poor (scores trained in EUR perform badly in EAS/AFR cohorts — a direct consequence of LD and allele-frequency differences); PRS is not a diagnostic; effect sizes in the discovery GWAS are themselves winner's-curse-biased (see interpretation reference).
