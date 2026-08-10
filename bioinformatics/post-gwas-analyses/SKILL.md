---
name: post-gwas-analyses
description: Post-GWAS analyses of summary statistics — annotation (ANNOVAR/VEP), heritability and genetic correlation (GCTA/LDSC), gene-based tests (MAGMA), fine-mapping (SuSiE), colocalization, meta-analysis, PRS, Mendelian randomization, TWAS, SMR/HEIDI. Use when the user has GWAS sumstats and asks about causal variants, heritability, functional annotation, polygenic risk.
metadata:
  author: Altair Wei
  version: "1.0"
license: MIT
---

# Post-GWAS Analyses

Turn a list of GWAS hits — or a full summary-statistics file — into biological and clinical insight: which variants are causal, how much heritability the trait has, which genes and pathways are involved, and whether risk can be predicted. This skill distills a hands-on GWAS tutorial (U. Tokyo, Laboratory of Complex Trait Genomics) into reproducible agent workflows.

## Working discipline

- **Confirm the sumstats manifest first.** Establish: columns (SNP ID, CHR/POS, effect allele, other allele, EAF, beta/OR, SE, P, N), genome build, whether the file is filtered (significance, MAF, info score), ancestry of the cohort, and whether an LD reference panel is available. Post-GWAS methods are merciless about format errors — a swapped effect allele silently inverts every downstream result.
- **Harmonize once, analyze many times.** Convert the sumstats to a clean standard (consistent allele coding, build, and column names) in a single preprocessing step before running any downstream tool; each tool in this skill then reads the same clean input.
- **Plan first, then track.** Turn the user's goal into an explicit step list (use the task list) and confirm it. The workflow map below is the menu; the user's question decides the selection.
- **One auditable command per step.** Run steps individually; verify each expected output file exists and is non-empty, and skim logs for warnings (LDSC prints intercept and ratio — read them).
- **Ground commands, don't recall them.** When unsure of a flag, check the tool's help or docs for the *installed* version before writing the command.
- **Decide with evidence, together.** Thresholds (PP.H4 > 0.8, credible-set size, PGS p-value thresholds, gene-set P cutoff) are judgment calls — present the evidence and let the user pick.
- **Keep provenance.** One experiment per run under `experiments/YYYY-MM-DD/`; scripts in `scripts/`; a `runall` records the command sequence; outputs in `results/`. Never modify raw sumstats.

## Workflow map

Each analysis answers a specific question. Load only the reference you need.

| If the user wants to know… | Analysis | Reference |
|---------------------------|----------|-----------|
| What do my hits affect? (function, consequence) | ANNOVAR / VEP annotation | annotation |
| How much heritability? / genetic correlation? | GCTA-GREML or LDSC | heritability |
| Which genes / gene sets? | MAGMA | gene-based |
| Which variant is causal? | SuSiE fine-mapping | finemapping-conditional |
| Is this a new signal or the known one? | GCTA-COJO conditional analysis | finemapping-conditional |
| Do two traits share a causal variant? | coloc | finemapping-conditional |
| Combine my study with others | meta-analysis (METAL/GWAMA/MR-MEGA) | meta-analysis |
| Predict individual risk | polygenic risk scores (PGS) | prs |
| Does the exposure cause the outcome? | Mendelian randomization (TwoSampleMR) | mr-twas-smr |
| Which gene is causal via expression? | TWAS (FUSION) / SMR | mr-twas-smr |
| Are my published effect sizes inflated? | winner's curse correction | interpretation |

**Prerequisites for every analysis:** see `sumstats-basics` — standardizing alleles, positions, and effect sizes, plus choosing an LD reference panel matched to the cohort ancestry.

## Key decision rules

- **Heritability:** GREML needs individual-level genotypes; LDSC works from sumstats alone. If you have both, GREML is more accurate for a single cohort; LDSC enables cross-trait rg and partitioned heritability.
- **Fine-mapping vs conditional analysis:** conditional analysis (COJO) *separates independent signals* in a locus; fine-mapping (SuSiE) *identifies the most likely causal variant(s)* within the signal. They answer different questions — run both when the user wants a full locus report.
- **Colocalization** answers "same variant drives both traits?" — it is the appropriate test before claiming two GWAS findings share a mechanism, and it is a precondition for credible cross-trait causal inference.
- **MR** is only as good as its instruments: clump to independence, check instrument strength (F > 10), and run sensitivity analyses (MR-Egger intercept, heterogeneity, leave-one-out) — report them, not just the IVW estimate.
- **PRS** built and validated in the same cohort are meaningless (winner's curse inflates them). Always validate in an independent sample; report R² / AUC *in the validation sample*.
- **Never meta-analyze before harmonizing** alleles and strand (palindromic SNPs!), or you will silently cancel real signals.

## Concept map

- Winner's curse and bias taxonomy (confounding, measurement, selection, analysis-induced) — interpretation
- Heritability concepts: broad/narrow sense, SNP heritability, liability-scale conversion — heritability
- LD as the connective tissue of every post-GWAS method — sumstats-basics, finemapping-conditional
