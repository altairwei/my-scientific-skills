---
name: gwas-association-testing
description: GWAS association analysis — genotype QC, PCA stratification, phasing/imputation prep, and association testing with PLINK, REGENIE, SAIGE, and LMM. Trigger on PLINK (bed/bim/fam), pgen, or VCF data with phenotypes — association tests, case-control or quantitative trait analysis, quality control, Firth regression, genomic control, Manhattan/QQ plots, or pre-GWAS processing.
metadata:
  author: Altair Wei
  version: "1.0"
license: MIT
---

# GWAS Association Testing

Run genome-wide association studies the way an experienced statistical geneticist would: confirm the data manifest before touching anything, QC before any testing, correct for population structure, and verify every intermediate result. This skill distills a hands-on GWAS tutorial (U. Tokyo, Laboratory of Complex Trait Genomics) into reproducible agent workflows. Standard regression assumes unrelated, ethnically homogeneous samples — the whole workflow before the association test exists to make that assumption true or to replace the model.

## Working discipline

- **Confirm the data manifest first.** Establish: genotype format (PLINK binary bed/bim/fam, pgen, VCF, BGEN), sample count, population structure (single or multiple ancestries), phenotype file (binary or quantitative, file columns), covariates, and genome build (hg19 vs hg38). Every downstream choice — filters, model, significance interpretation — depends on these. Ask the user when any are missing.
- **Plan first, then track.** Turn the goal into an explicit step list (use the task list) and confirm it with the user. The workflow map below is the menu; the user's question decides the selection.
- **One auditable command per step.** Run steps individually through the shell. Do not chain the whole pipeline into one script — tools fail silently inside pipes and a failed middle step corrupts everything downstream.
- **Verify outputs after every step.** Check that each expected file exists and is non-empty, and read the log: PLINK logs the sample/variant counts after filtering — they are your first sanity check. Skim for warnings before moving on.
- **Ground commands, don't recall them.** When unsure of a flag, run `plink --help` / `plink2 --help` / `regenie --help` for the *installed* version before writing the command. Tool flags drift between versions; the binary does not lie.
- **Debug with full context.** When a step fails, read the actual stderr/log, compare against the reference's decision rules, fix, and retry. After 2–3 failed repairs, stop and report the diagnosis — do not loop silently.
- **Decide with evidence, together.** Threshold choices (MAF, missingness, number of PCs, significance level) are judgment calls. Present the evidence and let the user pick.
- **Keep provenance.** Run the analysis as one experiment under `experiments/YYYY-MM-DD/`; reusable scripts live at the project's `scripts/`, a `runall` records the command sequence, outputs go in the experiment's `results/`. Never modify raw input files. *(See the bioinfo-project-organization skill for the full project layout.)*

## Workflow map

The canonical full workflow. Each step names the reference that covers it — load only what the current task needs.

| # | Step | Reference |
|---|------|-----------|
| 1 | Genotype QC (missingness, MAF, HWE, heterozygosity, relatedness, LD pruning) | data-qc |
| 2 | PCA + PC projection (stratification correction) | pre-gwas-processing |
| 3 | Phasing / imputation / liftover / chrX handling | pre-gwas-processing |
| 4 | Association testing (PLINK `--glm`, model choice, genomic control) | association-models |
| 5 | Visualization (Manhattan / QQ / regional) + result QC | association-models |
| 6 | Advanced models: REGENIE, SAIGE, LMM, rare-variant, nonlinear | advanced-methods |

Focused shortcuts by goal:

- "Just QC / filter genotype data" → data-qc only
- "Full association analysis" → data-qc → pre-gwas-processing (PCA) → association-models
- "Huge cohort / related samples / biobank-scale" → data-qc (through relatedness), then advanced-methods (REGENIE or SAIGE)
- "Imbalanced case-control (e.g. 1:10+)" → data-qc, then advanced-methods (SAIGE) or association-models (PLINK with Firth)

## Key decision rules

- **Model choice, in order of preference:** standard linear/logistic regression (PLINK `--glm`) on unrelated samples → linear mixed models or REGENIE/SAIGE when samples are related or ancestry is complex → rare-variant set tests when variants are rare. Switching models is an *a priori* design decision, not a fix for inflated results.
- **Firth correction:** needed for binary traits with unbalanced case-control ratios or when any tested variant has few minor-allele carriers. It penalizes the likelihood to reduce bias in parameter estimates. For balanced case-control (roughly 1:1) the standard likelihood converges fine.
- **Genomic control λ_GC ≈ 1.0** is the expectation for a well-behaved analysis. λ much above 1.0 signals stratification, cryptic relatedness, or model misspecification — diagnose before reporting results. Note the assumption fails for highly polygenic traits.
- **Never report or interpret a P value without knowing which allele it refers to** (A1 = effect allele), whether the model was linear or logistic, and what covariates were adjusted for.
- **Significance:** genome-wide P < 5×10⁻⁸ (Bonferroni for ~1M independent tests); P between 1×10⁻⁵ and 5×10⁻⁸ is "suggestive" and needs replication.
- **Manhattan/QQ plots:** use a mature package like [`gwaslab`](https://github.com/Cloufield/gwaslab); never hand-roll downsampling of null variants (it carves a density cliff into the haze). Plot every point and control PDF size by rasterizing, not subsampling. See association-models for the full rule.

## Concept map

The references also carry the statistical genetics background needed to *interpret* results, not just run commands:

- Linkage disequilibrium (D, D′, r², what affects it) — data-qc, association-models
- Genetic models (additive/dominant/recessive), effect measures (OR, RR, HR) — association-models
- Multiple testing (Bonferroni, FDR, 5×10⁻⁸ rationale) — association-models
- Statistical power (NCP, what drives it) — association-models
- Population stratification and cryptic relatedness — pre-gwas-processing, association-models
- Phenotype normalization (z-score, rank-based INT) — association-models
- Heritability concept (narrow/broad sense, liability scale) — advanced-methods
