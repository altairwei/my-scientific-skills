---
name: population-genomics
description: Population-genomics workflows for PLINK, ADMIXTURE, smartpca, TreeMix, ADMIXTOOLS, easySFS, and fastsimcoal2. Use when the user shares VCF or PLINK (bed/bim/fam) data and asks about population structure, PCA, ancestry/admixture, ROH, heterozygosity, LD decay, FST, f3/f4/D-statistics, gene flow, or demographic history.
metadata:
  author: Altair Wei
  version: "1.0"
license: MIT
---

# Population Genomics

Analyze population-genetic variation data — VCF or PLINK binary (bed/bim/fam) — the way an experienced analyst would: plan from the question, run one auditable step at a time, verify every output, and interpret the figures yourself. This skill is distilled field experience, not a fixed pipeline: a full study touches everything below, but most questions need only a focused slice.

## Working discipline

These habits are what separate a reliable analysis from a plausible-looking one. Follow them for every task in this domain.

- **Confirm the data manifest before running anything.** Establish: input format (VCF vs PLINK binary), sample count, population/group labels, and whether a population-map file exists. Ask the user when any of these are missing — every downstream choice depends on them.
- **Plan first, then track.** Turn the user's goal into an explicit step list (use the task list) and confirm it with the user. The workflow map below is the menu; the user's question decides the selection.
- **One auditable command per step.** Run steps individually through the shell; do not chain the whole pipeline into one script. Population-genomics tools fail silently inside pipes, and a failed middle step corrupts everything after it.
- **Verify outputs after every step.** Check that each expected file exists and is non-empty, and skim the tool's log for warnings before moving on. Each reference lists the expected outputs per analysis.
- **Ground commands, don't recall them.** When unsure of a flag, run `<tool> --help` or check the official docs for the *installed* version before writing the command. Memory of tool flags drifts; the binary does not lie.
- **Debug with full context.** When a step fails, read the actual stderr/log, compare against the reference's decision rules, fix, and retry. After 2–3 failed repairs, stop and report the diagnosis — do not loop silently.
- **Decide with evidence, together.** Choices like best K (ADMIXTURE), number of migration edges (TreeMix), or SFS projection sizes are judgment calls. Present the evidence table (CV errors, likelihoods) and let the user pick.
- **Keep provenance.** Run the analysis as one experiment under `experiments/YYYY-MM-DD/`; reusable scripts live at the project's `scripts/`, the experiment's `runall` records the command sequence, and outputs go in the experiment's `results/`. Never modify the raw input files. *(See the bioinfo-project-organization skill for the full project layout.)*

## Workflow map

The canonical full workflow. Each step names the reference that covers it — load only what the current task needs.

| # | Step | Reference |
|---|------|-----------|
| 1 | Quality filtering (MAF, missingness, biallelic) | preprocessing-and-qc |
| 2 | LD pruning round 1 (r² 0.2 — for kinship & diversity stats) | preprocessing-and-qc |
| 3 | Kinship detection (KING) | preprocessing-and-qc |
| 4 | Remove related individuals | preprocessing-and-qc |
| 5–6 | ROH + visualization | diversity-statistics |
| 7–8 | Heterozygosity + visualization | diversity-statistics |
| 9–10 | LD decay + visualization | diversity-statistics |
| 11 | LD pruning round 2 (r² 0.1, stricter — for PCA/ADMIXTURE) | preprocessing-and-qc |
| 12–14 | EIGENSTRAT conversion + smartpca + PCA plot | population-structure |
| 15–16 | ADMIXTURE K sweep + CV selection + bar plot | population-structure |
| 17–19 | TreeMix input prep + m sweep + tree plot | treemix-and-fstatistics |
| 20 | f3/f4/D-statistics (ADMIXTOOLS) | treemix-and-fstatistics |

Focused shortcuts by goal:

- "Just QC / filter / convert formats" → preprocessing-and-qc only
- "PCA / population structure / ancestry" → preprocessing-and-qc (QC + pruning), then population-structure
- "Diversity / ROH / inbreeding / LD decay / FST" → preprocessing-and-qc (through relatedness removal), then diversity-statistics
- "TreeMix / migration / gene flow / f-statistics" → treemix-and-fstatistics (inputs need the pruned set from preprocessing-and-qc)
- "Demographic history / SFS / fastsimcoal" → demographic-inference

## Data contract

- **Inputs**: PLINK binary triplets (`.bed/.bim/.fam`) or VCF/BCF. Convert VCF → PLINK early when the task needs PLINK-based tools (see preprocessing-and-qc).
- **Population map**: many analyses (per-population LD decay, TreeMix, ADMIXTURE plotting, easySFS) need a sample→population file. Derive it from the `.fam` or ask the user.
- **Output layout**: each analysis session is one experiment directory under `experiments/YYYY-MM-DD/` with its `runall` and `results/`. Never write outputs next to the raw data.
- **Raw data is immutable**: filtering and conversion always write new files; never edit inputs in place.

## References (load on demand)

Read these files only when the current task reaches them. Each is self-contained for its tools, including file-format specs.

- `references/preprocessing-and-qc.md` — VCF↔PLINK conversion, QC thresholds, two-round LD pruning, KING kinship tiers, relatedness removal
- `references/diversity-statistics.md` — ROH, observed heterozygosity, per-population LD decay, FST; reading the resulting plots
- `references/population-structure.md` — EIGENSTRAT conversion, smartpca, ADMIXTURE K selection; reading PCA biplots and ancestry bar plots
- `references/treemix-and-fstatistics.md` — TreeMix input/m sweep/rooting, f3/f4/D interpretation, qpAdm/qpGraph pointers
- `references/demographic-inference.md` — easySFS projection, fastsimcoal2 .tpl/.est grammar and anti-hang rules, likelihood-driven model search, Demes export

## Further analyses (pointers only)

For requests beyond the core workflow, state what is involved and consult official docs before proceeding:

- **qpAdm / qpGraph** — formal admixture-model fitting in ADMIXTOOLS; data setup is shared with f-statistics (see treemix-and-fstatistics).
- **PSMC / MSMC** — coalescent Ne-history inference from whole diploid genomes; needs per-sample consensus sequences, not SNP panels.
- **Selection scans (iHS, XP-EHH)** — selscan on phased haplotypes; phasing (SHAPEIT/Beagle) is a prerequisite the core workflow does not cover.

## Rules

- Show real numbers from real outputs — never state a finding (best K, significant D, expansion signal) you did not compute from the files.
- Sample sizes shrink after QC and relatedness removal — re-check per-population counts after each filtering step and warn the user when a population drops below what the statistic needs (roughly: LD decay ≥ 20, ADMIXTURE/TreeMix ≥ 5, f-stats ≥ 2, and treat any singleton result as exploratory).
- Figures are deliverables: save them to files, then Read and interpret them — a plot nobody looked at is not a result.
- Record the exact commands and parameter choices (thresholds, K range, m range) in the experiment's `runall` and the `lab-notebook.md` entry — not just a final summary — so the analysis is reproducible.
