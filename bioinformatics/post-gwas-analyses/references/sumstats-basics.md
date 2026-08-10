# Summary Statistics: Standardization and LD Reference

Load before any post-GWAS analysis — every downstream tool in this skill assumes a clean, standardized sumstats file and an appropriate LD reference panel.

## Table of contents

- [The standardization pass](#the-standardization-pass)
- [Allele harmonization traps](#allele-harmonization-traps)
- [LD reference panels](#ld-reference-panels)

## The standardization pass

Post-GWAS tools are merciless about format. Before running any of them, convert the user's raw sumstats into one canonical file with at least these columns, documented in a header:

| Field | Notes |
|-------|-------|
| SNP | rsID or chr:pos:ref:alt — pick one and be consistent |
| CHR / BP | same genome build everywhere (hg19 vs hg38); liftover if mixing |
| A1 (effect allele) | the allele the effect refers to |
| A2 (other allele) | |
| EAF | frequency of A1 |
| BETA or OR | log-odds for binary; keep β, not OR, for meta-analysis and fine-mapping |
| SE | needed for meta-analysis, fine-mapping, LDSC |
| P | |
| N | per-variant sample size (some cohorts drop samples per variant) |

Do this in one preprocessing step (a small script is fine — awk/pandas), never per-tool. Tools that need extra columns (e.g. LDSC's N or case fraction, MAGMA's N) read them from this canonical file.

## Allele harmonization traps

These are the dominant source of silent errors in real post-GWAS work:

- **Effect-allele flips:** if tool A reports effect on A but tool B expects effect on T, every statistic is inverted. Standardize by making A1 = effect allele and documenting it; when merging studies, flip β and EAF whenever the effect allele differs.
- **Palindromic SNPs (A/T, C/G):** strand cannot be inferred from alleles alone. When harmonizing across studies, resolve palindromics by frequency matching (EAF), by LD tagging, or drop them — and report how many were dropped.
- **A1/A2 vs REF/ALT:** PLINK 1.9's A1 is frequency-based minor allele; PLINK 2 / VCF REF/ALT is genome-consensus-based; some cohorts use risk/effect allele. They do not agree in general. Verify against the study's own documentation, not by guesswork.
- **Strand:** a G→A in a plus-strand genome is C→T on the minus strand. Unless you know the cohort's strand convention, ambiguous palindromics are the safe place to require explicit resolution.
- **Coordinate systems:** GWAS sumstats are 1-based inclusive; BED-based tools are 0-based half-open. Off-by-one errors land variants in the wrong LD block or wrong gene window.

## LD reference panels

Most post-GWAS tools (LDSC, MAGMA, SuSiE-RSS, COJO, SMR, LDSC-SEG) need LD estimated from *individual genotypes* — which you usually no longer have. The substitute is an external reference panel of the **same ancestry** as the study cohort:

- **1000 Genomes Phase 3** (European/EAS/AFR/AMR/SAS panels) — the standard default; w_hm3 (HapMap3 SNP subset, ~1.2M variants) is the canonical SNP set for LDSC.
- **TOPMed** (large, diverse, deep sequencing) — better for rare variants and admixed populations.
- **UK Biobank / cohort-specific panels** — best when available and ancestry-matched.

Decision rules:

- Match ancestry to the cohort: an EAS cohort needs the EAS panel, not CEU — mismatched LD biases heritability and fine-mapping estimates.
- Precomputed LD score files (e.g. `eas_ldscores/`, `eur_w_ld_chr/`) exist for the standard panels; do not recompute unless a nonstandard panel is required.
- If the cohort has no matching panel (admixed, isolated populations), say so explicitly and discuss the bias with the user before proceeding — this is a real limitation, not a format detail.
