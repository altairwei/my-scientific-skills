# Genotype Data QC

Load when the user has raw genotype data (PLINK bed/bim/fam, pgen, VCF, BGEN) and needs QC, filtering, relatedness checks, or format conversion before any association testing.

## Table of contents

- [Data formats](#data-formats)
- [QC workflow](#qc-workflow)
- [Thresholds at a glance](#thresholds-at-a-glance)
- [Reference commands](#reference-commands)
- [Naming and coordinate traps](#naming-and-coordinate-traps)

## Data formats

Know what you are working with before QC:

| Format | What it stores | Notes |
|--------|----------------|-------|
| PLINK binary `.bed/.bim/.fam` | genotypes, 2 bits per variant per sample | the workhorse; PLINK 1.9 reads this natively |
| PLINK 2 `.pgen/.psam/.pvar` | genotypes + dosages, haploid support | faster, larger variant set; `plink2` only |
| VCF | variants + genotypes/dosages per sample | text-based, portable; convert with `plink2 --vcf` |
| BGEN | genotype probabilities / dosages | common for imputed data; `plink2 --bgen` |
| Text `.ped/.map` | genotypes as allele pairs | convert to binary with `--make-bed` |

Genotypes (hard calls) vs dosages (expected allele count, 0–2 continuous) matter downstream: imputed data is analyzed on dosage, array data on hard calls. Always check the `.bim` allele coding before anything else (see traps below).

## QC workflow

QC protects association tests from two kinds of garbage: **bad variants** (genotyping errors, assay failures) and **bad samples** (low call rate, contamination, sex mismatches, duplicates/relatedness). The order matters — filter variants first, then samples, then relatedness:

1. **Variant-level**: compute missing rate (`--missing`), allele frequency (`--freq`), Hardy-Weinberg (`.hardy`), then filter with `--maf`, `--geno`, `--hwe`.
   - MAF filter removes variants that carry no information at realistic effect sizes and are prone to genotyping error.
   - HWE filter: deviation from HWE is a genotyping-error signature in case-control samples (in *cases* deviation can be real signal — apply HWE to controls or use a case-control-aware threshold; the common practice is to filter on controls or use a lenient threshold).
2. **Sample-level**: missing rate (`--mind`), heterozygosity (`--het` on LD-pruned SNPs) to catch contamination and sample mix-ups.
   - F_het far from 0 (e.g. |F| > 0.1–0.15, or >3 SD from the mean) → contaminated or mislabeled sample; remove.
3. **Relatedness**: `--genome` (IBD) on pruned SNPs for PLINK 1.9, or KING (`plink2 --make-king-table` / `--king-cutoff`) — KING is preferred for heterogeneous cohorts. Remove duplicates and close relatives unless your analysis plan uses LMM.
4. **LD pruning** (`--indep-pairwise`): subsets SNPs to approximate independence — required before heterozygosity/IBD/PCA/GRM steps.
5. **Final clean set** (`--make-bed`) with your chosen filters, plus `--keep-allele-order` so alleles never get silently swapped.

Sex check: `plink --check-sex` uses X-chromosome heterozygosity (males ~1, females ~0) — mismatch means sample mix-up, fix or drop.

## Thresholds at a glance

These are typical defaults from large-cohort practice; the tutorial uses the values in parentheses:

| Filter | Common threshold | Notes |
|--------|------------------|-------|
| SNP missingness `--geno` | 0.01–0.05 (tutorial: 0.01) | imputed data: often 0.02 on top of Rsq filter |
| Sample missingness `--mind` | 0.01–0.02 | strict in the tutorial; 0.05–0.1 acceptable for big cohorts |
| MAF `--maf` | 0.01 | 0.05 if rare variants are not of interest |
| HWE `--hwe` | 1e-6 (p-value, PLINK 1.9 default 0.001) | apply to controls when case-control |
| Heterozygosity F | |F| > 0.15 or 3 SD | on LD-pruned SNPs only |
| IBD PI_HAT | > 0.2 (2nd degree) | `--genome` output; pairwise removal |
| KING kinship | > 0.0884 (2nd degree) | `--king-cutoff 0.0884`; also 0.354 dup/MZ, ~0.177 1st, ~0.044 3rd degree |
| LD pruning | `--indep-pairwise 50 5 0.2` | window 50 SNPs, step 5, r² 0.2; stricter (0.1, 0.02) for PCA |
| MAF for pruning/PCA | 0.01–0.05 | |

Hardy-Weinberg: `plink --hardy` reports the exact test (Wigginton 2005). Inbreeding coefficient F = (O(HOM) − E(HOM)) / (M − E(HOM)).

## Reference commands

```bash
# --- Step 1: basic stats (decide filters from the output) ---
plink --bfile raw_data --missing --freq --hardy --out qc_stats

# --- Step 2: variant + sample filtering + LD pruning ---
plink --bfile raw_data \
    --maf 0.01 --geno 0.01 --mind 0.02 --hwe 1e-6 \
    --indep-pairwise 50 5 0.2 \
    --out qc_filtered

# --- Step 3: heterozygosity (on pruned SNPs) ---
plink --bfile raw_data --extract qc_filtered.prune.in --het --out qc_het
# flag samples with |F_het| > 0.1; write them to high_het.sample (FID IID)

# --- Step 4: relatedness (on pruned SNPs) ---
plink --bfile raw_data --extract qc_filtered.prune.in --genome --out qc_ibd
# PLINK 2 / KING (preferred for multi-ancestry):
plink2 --bfile raw_data --make-king-table --out qc_king

# --- Step 5: final clean dataset ---
plink --bfile raw_data \
    --geno 0.02 --mind 0.02 --hwe 1e-6 \
    --remove high_het.sample \
    --keep-allele-order --make-bed \
    --out sample_data.clean
```

Check the `.log` after every step: PLINK prints variants/samples loaded, removed per filter, and remaining — verify each count is sensible before proceeding.

For imputed dosage data, add an imputation-quality filter instead of/in addition to MAF: `plink2 --mach-r2-filter 0.7 2.0` (upper bound 2.0 for pgen dosages).

## Naming and coordinate traps

These are the most common sources of silent errors in real GWAS work:

- **Allele naming is inconsistent across tools.** Three naming families coexist: (1) major/minor — frequency-based, PLINK 1.9 reports A1 = minor by default; (2) REF/ALT — genome-consensus-based, PLINK 2 and VCF; (3) effect/risk allele — association-test-based. `A1`/`A2` from one tool may not equal `REF`/`ALT` from another. Always know which allele the effect estimate refers to before comparing or merging datasets.
- **Genome builds:** positions are meaningless across hg19/hg38. Verify the build in the `.bim`/`.vcf` header; convert with liftOver if merging different-build data (see pre-gwas-processing).
- **Coordinate systems:** VCF/GWAS sumstats use 1-based inclusive coordinates; BED/UCSC use 0-based half-open. Converting means ±1 — a classic off-by-one.
- **Palindromic SNPs (A/T, C/G):** strand ambiguity breaks allele harmonization; handle explicitly when merging sumstats or cross-ancestry data.
- **`.bim` allele order in PLINK 1.9** is major/minor (frequency order) unless `--keep-allele-order` is used — which is why QC and all downstream steps should pass it.

## Relatedness decision rules

If the cohort contains relatives and the analysis will use standard regression: remove to 2nd-degree relatedness (KING cutoff 0.0884). If relatives are the point of the study, or removal would destroy power, plan for LMM (see advanced-methods) from the start.
