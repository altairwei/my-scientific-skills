# Pre-GWAS Processing: PCA, Phasing, Imputation, Liftover

Load when the user needs population-structure correction (PCA), haplotype phasing, imputation, genome-build conversion (liftover), or sex-chromosome handling before association testing.

## Table of contents

- [PCA for population stratification](#pca-for-population-stratification)
- [Phasing](#phasing)
- [Imputation](#imputation)
- [Liftover](#liftover)
- [chrX handling](#chrx-handling)

## PCA for population stratification

Association tests assume samples are drawn from one homogeneous population. Real cohorts mix ancestries; unless controlled, false positives appear wherever allele frequency tracks ancestry. PCA converts genome-wide genetic similarity into a handful of covariates (PCs) that soak up this structure.

**Workflow:**

1. **LD-prune strictly** for PCA (tight LD inflates the eigenvectors of a few regions): `--indep-pairwise 500 50 0.2` with `--maf 0.01` — or reuse the QC prune set.
2. **Exclude high-LD regions** (MHC/HLA, inversions) which otherwise dominate the top PCs: `--make-set` from a regions list, then `--exclude`.
3. **Remove relatives** (`--king-cutoff 0.0884`) — related individuals distort PCA.
4. **Compute PCs on the unrelated subset** with per-variant weights: `plink2 --pca approx allele-wts 10`.
5. **Project** the remaining samples onto those eigenvectors: `plink2 --score <allele-wts> 2 5 header-read no-mean-imputation`.

```bash
plink2 --bfile sample_data.clean --indep-pairwise 500 50 0.2 --maf 0.01 --out pca_prune
plink2 --bfile sample_data.clean --extract pca_prune.prune.in \
       --make-king-table --out pca_king          # → unrelated.sample.id
plink2 --bfile sample_data.clean --extract pca_prune.prune.in \
       --keep unrelated.sample.id \
       --pca approx allele-wts 10 --out pca_results
plink2 --bfile sample_data.clean --score pca_results.eigenvec.allele 2 5 header-read no-mean-imputation \
       --out pca_projected
```

**Decision rules:**

- 10 PCs is a common default for homogeneous cohorts; use 20 for multi-ancestry or admixed samples.
- The projected `.sscore` file (PC1_AVG … PC10_AVG columns) is the covariate file for association testing. PLINK 2's `--pca` header uses `PC1_AVG` naming; REGENIE's `--covarColList` accepts the same names.
- A scree plot (eigenvalue drop-off) tells you how many PCs matter — the "elbow" is a reasonable stop point.
- Watch for PCs that separate known continental ancestries (e.g. CHB vs JPT in the 1KG EAS sample): that is real structure that *must* be adjusted for.
- UMAP/t-SNE are useful for visualization of fine structure, but PCs are what go into the model.

## Phasing

Phasing determines which chromosome each allele came from (haplotype reconstruction) — a prerequisite for imputation, HLA analysis, and haplotype-based tests. Phasing uses the local LD structure to "guess" haplotypes with high accuracy.

**Tools:** Eagle2 (fast, recommended for large samples), SHAPEIT2/4, or `plink2 --phase`.

**Workflow sketch:**

1. Align genotypes to a reference: `plink2 --ref-from-fa --fa <reference.fa>` (fixes strand issues).
2. Subset to the target chromosome/region if processing by chromosome (standard practice).
3. Run the phaser; typical invocation: `eagle2 --bfile <subset> --outPrefix phased` or `shapeit2 --input-bed ... --output-max ...`.
4. Output phased VCF for imputation: `bcftools convert --haplotype-to-vcf` or the phaser's own VCF output.

Phasing quality matters downstream — imputation of a misphased sample is garbage in, garbage out. Check the phaser's switch-error/quality statistics.

## Imputation

Imputation predicts variants that were not genotyped, using the LD structure of a reference panel. It is what makes cross-study meta-analysis and fine-mapping possible on array data, and it is required to test variants not present on the array.

**The standard pipeline** (typically run through a server like Michigan/TOPMed/Sanger):

1. **Prepare**: phased, build-checked (liftOver if needed), strand-aligned per-chromosome VCFs.
2. **Submit** to an imputation server or run locally (minimac4/IMPUTE5) against a reference panel matched to the sample ancestry — the closest panel gives the best accuracy (e.g. EAS panel for East Asian samples, not CEU).
3. **Post-process**: `plink2 --vcf <imputed.vcf.gz> --make-pgen --out imputed` and apply quality filters:
   - Rsq (imputation quality, aka MaCH-R²): keep `Rsq ≥ 0.3` for common variants, `≥ 0.8` for rare; the tutorial uses `--mach-r2-filter 0.7 2.0`.
   - MAF: array-based filters (0.01) are often too strict for imputed rare variants — consider `--mac` (minor allele count) instead when the sample size supports it.
   - Missingness: `--geno 0.02`.

Imputed data is analyzed on **dosages**, not hard calls: `plink2 --glm` accepts pgen dosages directly; REGENIE reads BGEN/pgen natively.

## Liftover

Genome builds change; coordinates do not transfer. Convert all data (genotypes, sumstats, annotations) to a single build before any analysis that merges datasets.

**Tools:** UCSC `liftOver` (chain-file based), CrossMap, Picard `LiftoverVcf`.

```bash
liftOver <input.bed> <hg19ToHg38.over.chain.gz> <output.bed> <unmapped.bed>
```

**Failure modes** (report unmapped positions, don't silently drop them): telomeres, centromeres, ALT contigs, segmental duplications, many-to-one collapse, indel compression, and strand issues. UCSC and NCBI chain files can disagree on remapping — pick one convention and document it. For variant-level liftover use a variant mapper (e.g. `bcftools liftover` with a chain + fasta) rather than position-only lifting.

## chrX handling

The X chromosome has pseudoautosomal regions (PAR1/PAR2) that behave like autosomes, and a non-PAR region that is diploid in females, haploid in males. Analysis must treat them separately:

1. **Split PAR/non-PAR**: `plink2 --split-par hg38` (or `hg19`).
2. **Sex check**: `plink --check-sex` (X inbreeding F ≈ 1 in males, ≈ 0 in females) — mismatches are sample mix-ups.
3. **Dosage encoding**: PLINK encodes haploid males as 0/2; make sure the analysis tool handles this (PLINK 2 and REGENIE do).
4. PAR boundaries: hg19 chrX:60,001–2,699,520 and 154,931,044–155,260,560; hg38 chrX:10,001–2,781,479 and 155,701,383–156,030,895.
5. Chromosome encodings differ across tools (e.g. GWAS-SSF: X=23, Y=24, MT=25; PLINK 1.9: X=23, Y=24, XY=25, MT=26) — normalize when merging.
