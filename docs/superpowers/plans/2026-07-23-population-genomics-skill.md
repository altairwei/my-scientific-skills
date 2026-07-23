# `population-genomics` Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `bioinformatics/population-genomics` skill — five self-contained reference files plus a workflow-map SKILL.md — distilling PopGenAgent's population-genomics expertise, then register it in the marketplace and README.

**Architecture:** Per the approved spec (`docs/superpowers/specs/2026-07-23-population-genomics-skill-design.md`): SKILL.md carries the Claude-Code-adapted working discipline and a 20-step workflow map; `references/*.md` carry per-topic command templates, decision rules, output-verification checklists, figure-reading guides, and pitfalls. No `scripts/` directory. All content is original; third-party tools are referenced, never vendored.

**Tech Stack:** Markdown skill files (agentskills.io frontmatter spec); PLINK/PLINK2, KING, EIGENSOFT smartpca, ADMIXTURE, TreeMix, ADMIXTOOLS (R), easySFS, fastsimcoal2, Demes as documented tools; `count-skill-tokens.py` for size verification; `marketplace.json` + `README.md` for registration.

**Source material:** The distilled command patterns and decision rules below come from the PopGenAgent survey (see spec's "Source analysis" section). Executors do NOT need to re-read `external/POPGENAGENT` — every file's complete content is embedded in this plan.

---

### Task 1: Create `SKILL.md`

**Files:**
- Create: `bioinformatics/population-genomics/SKILL.md`

- [ ] **Step 1: Write `bioinformatics/population-genomics/SKILL.md` with exactly this content**

````markdown
---
name: population-genomics
description: Population-genomics analysis workflows for PLINK, ADMIXTURE, smartpca, TreeMix, ADMIXTOOLS, easySFS, and fastsimcoal2. Use whenever the user shares VCF or PLINK (bed/bim/fam) data and asks about population structure (群体结构), PCA, ancestry/admixture, ROH, heterozygosity, LD decay, FST, f3/f4/D-statistics, gene flow, or demographic history — even when they only name the analysis ("run ADMIXTURE", "做个PCA").
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
- **Keep provenance.** Work in a dedicated output directory, keep generated scripts and logs next to results, and never modify the raw input files.

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
- **Output layout**: create one output directory per analysis session (e.g. `popgen-output/`) with subdirectories per analysis. Never write outputs next to the raw data.
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
- Record the exact commands and parameter choices (thresholds, K range, m range) in the final summary so the analysis is reproducible.
````

- [ ] **Step 2: Verify size limits**

Run: `./count-skill-tokens.py bioinformatics/population-genomics`
Expected: no `⚠️` markers. Description ≤ 100 tokens; SKILL.md ≤ 5000 tokens / 500 lines. If the description exceeds 100 tokens, trim parenthetical examples first (e.g. drop `"做个PCA"`, then `(群体结构)`) and re-run.

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/population-genomics/SKILL.md
git commit -m "Add population-genomics SKILL.md with workflow map and working discipline"
```

---

### Task 2: Create `references/preprocessing-and-qc.md`

**Files:**
- Create: `bioinformatics/population-genomics/references/preprocessing-and-qc.md`

- [ ] **Step 1: Write the file with exactly this content**

````markdown
# Preprocessing and Quality Control

Population-genetics statistics assume independent, high-quality SNPs genotyped in unrelated individuals. Skipping or reordering these steps invalidates downstream numbers in ways that are hard to detect later — a kinship estimate computed on LD-correlated SNPs, or a PCA run on related individuals, looks fine but means something else.

## When to use

Read this when the task involves: converting VCF ↔ PLINK formats, filtering variants or samples, LD pruning, or detecting/removing related individuals (KING, kinship, `.kin0`).

## Command templates

In all templates, replace `OUTDIR` with the session output directory. Verify tool availability first (`which plink king`); if missing, propose `conda install -c bioconda plink king` and wait for consent.

### VCF → PLINK binary

```bash
plink --vcf input.vcf.gz --double-id --allow-extra-chr \
  --set-missing-var-ids @:# --make-bed --out OUTDIR/raw
```

- `--double-id` copies the sample name into both ID fields (VCF has no two-ID structure).
- `--set-missing-var-ids @:#` names unnamed variants `chr:pos` — required because many downstream steps key on variant ID.
- `--allow-extra-chr` is for non-human assemblies; drop it for human data.
- For BCF or large VCFs, `plink2 --vcf` or `bcftools` conversion is faster; the flags above are PLINK 1.9.

### Quality filtering

```bash
plink --bfile OUTDIR/raw \
  --maf 0.05 --geno 0.05 --mind 0.1 --biallelic-only strict \
  --make-bed --out OUTDIR/filtered
```

### LD pruning — two rounds, two purposes

Round 1 (r² = 0.2) — SNP set for kinship estimation and diversity statistics:

```bash
plink --bfile OUTDIR/filtered --indep-pairwise 50 5 0.2 --out OUTDIR/prune1
plink --bfile OUTDIR/filtered --extract OUTDIR/prune1.prune.in \
  --make-bed --out OUTDIR/ld_pruned1
```

Round 2 (r² = 0.1, stricter, applied to the *unrelated* set) — for PCA and ADMIXTURE, which assume unlinked markers:

```bash
plink --bfile OUTDIR/unrelated --indep-pairwise 50 5 0.1 --out OUTDIR/prune2
plink --bfile OUTDIR/unrelated --extract OUTDIR/prune2.prune.in \
  --make-bed --out OUTDIR/ld_pruned2
```

`--indep-pairwise 50 5 X` means: 50-SNP window, slide 5 SNPs per step, prune one of each pair with r² above X.

### Kinship detection and relatedness removal (KING)

```bash
king -b OUTDIR/ld_pruned1.bed --related --prefix OUTDIR/kinship
```

Then remove one member of each related pair. The `kinship.kin0` file has a header naming its columns (`FID1`, `ID1`, `FID2`, `ID2`, …, `Kinship`) — read the header rather than assuming fixed column positions, and choose the member with lower call rate (or more relatives) per pair. Feeding both members of every pair to `--remove` would delete entire families.

```bash
# after building related_to_remove.txt (one FID IID pair per line, one individual per pair)
plink --bfile OUTDIR/filtered --remove OUTDIR/related_to_remove.txt \
  --make-bed --out OUTDIR/unrelated
```

Modern one-step alternative: `plink2 --bfile OUTDIR/ld_pruned1 --king-cutoff 0.0884 --make-bed --out ...` implements KING-robust estimation with built-in greedy removal (cutoff 0.0884 ≈ up to 3rd-degree relatives).

## Parameter decision rules

**QC thresholds (defaults — adjust with a stated reason and record the choice):**

- `--maf 0.05`: removes rare variants that add noise to structure analyses. For diversity statistics on large cohorts, 0.01 is also defensible.
- `--geno 0.05`: drop SNPs with >5% missing calls; `--mind 0.1`: drop samples with >10% missing.
- `--biallelic-only strict`: multiallelic sites break ADMIXTURE/TreeMix/f-statistics assumptions.
- Filter samples and SNPs in one pass so thresholds apply jointly.

**Kinship coefficient (φ) tiers:**

| φ range | Relationship |
|---|---|
| > 0.354 | duplicate / monozygotic twin |
| 0.177–0.354 | 1st degree |
| 0.0884–0.177 | 2nd degree |
| 0.0442–0.0884 | 3rd degree |

**Ordering rationale:**

- Run KING on the round-1 LD-pruned set — relatedness estimates are inflated by LD.
- Remove relatives from the *filtered* (unpruned) set, keeping maximum SNP density for diversity statistics. The `unrelated` set feeds both diversity stats and round-2 pruning.
- PCA/ADMIXTURE get the stricter round-2 set; diversity statistics tolerate (and benefit from) more SNPs.

## Output verification checklist

- `filtered.{bed,bim,fam}` exist; SNP/sample counts in the PLINK log are lower than raw but not catastrophically (a >50% SNP drop usually means a threshold or chromosome-naming problem).
- `prune1.prune.in` / `prune2.prune.in` are non-empty. Empty output = threshold too strict for the data density or too few SNPs — loosen r² or widen the window.
- `kinship.kin0` exists. An empty (header-only) file means no related pairs — a valid result, not an error.
- After removal: `unrelated.fam` line count + removed count = `filtered.fam` line count.
- Report per-population sample counts after `unrelated`; flag any population that has collapsed.

## Figure reading guide

QC is mostly numeric, but two diagnostic plots are worth making when the data is unfamiliar:

- **MAF spectrum** (histogram of `--freq` output): a healthy panel has mass spread across frequencies; a huge spike near 0 after `--maf 0.05` suggests genotyping artifacts survived filtering.
- **Per-sample missingness vs heterozygosity** (from `--missing` + `--het`): outlier samples off the cloud = contamination, wrong species/relatives, or failed DNA — remove them before proceeding.

## Common pitfalls

- Forgetting `--set-missing-var-ids` → duplicate/missing variant IDs break `convertf` and TreeMix input preparation downstream.
- Pruning order: QC → prune1 → KING → remove → prune2. Removing relatives *before* KING (from the wrong file set) or pruning structure SNPs from the related set are the two classic mistakes.
- Chromosome naming mismatches (`chr1` vs `1`) between VCF and any auxiliary reference files silently drop all variants.
- `--mind` can remove many low-coverage samples — check *which* populations lost samples before proceeding.
````

- [ ] **Step 2: Check for leftover placeholders**

Run: `grep -nE "TBD|TODO|FIXME" bioinformatics/population-genomics/references/preprocessing-and-qc.md`
Expected: no output (exit 1).

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/population-genomics/references/preprocessing-and-qc.md
git commit -m "Add preprocessing-and-qc reference for population-genomics skill"
```

---

### Task 3: Create `references/diversity-statistics.md`

**Files:**
- Create: `bioinformatics/population-genomics/references/diversity-statistics.md`

- [ ] **Step 1: Write the file with exactly this content**

````markdown
# Diversity Statistics

Runs of homozygosity, heterozygosity, LD decay, and FST answer "how much variation, how is it structured, and how did drift act on it?" They are computed on the QC'd, relatedness-removed (`unrelated`) set — related individuals double-count segments and deflate diversity.

## When to use

Read this when the task involves ROH (runs of homozygosity, inbreeding, F_ROH), observed heterozygosity, LD decay curves, or FST between populations.

## Command templates

All commands assume `OUTDIR/unrelated` from preprocessing-and-qc. A population map (`popmap.txt`: one `IID <tab> POP` per line, derived from the `.fam` or supplied by the user) is needed for per-population work.

### Runs of homozygosity (ROH)

```bash
plink --bfile OUTDIR/unrelated --homozyg \
  --homozyg-snp 50 --homozyg-kb 500 --homozyg-density 50 \
  --homozyg-gap 1000 --homozyg-window-snp 50 \
  --homozyg-window-het 1 --homozyg-window-missing 5 \
  --out OUTDIR/roh_segments
```

Per-individual inbreeding: F_ROH = (sum of ROH lengths in kb, typically segments ≥ 500 kb–1 Mb) / (total genotyped autosomal length in kb; ≈ 2.88×10⁶ kb for human, scale to your species).

### Heterozygosity

```bash
plink --bfile OUTDIR/unrelated --het --out OUTDIR/heterozygosity_stats
```

The `.het` columns are `FID IID O(HOM) E(HOM) N(NM) F`. Observed heterozygosity rate = (`N(NM)` − `O(HOM)`) / `N(NM)`. The `F` coefficient: positive F = homozygote excess (inbreeding/drift), negative F = heterozygote excess (outbreeding/recent admixture).

### LD decay (per population)

```bash
plink --bfile OUTDIR/unrelated \
  --keep OUTDIR/POP_samples.txt \
  --r2 --ld-window 999999 --ld-window-kb 500 --ld-window-r2 0.0 \
  --out OUTDIR/ld_decay/POP_ld
```

Then bin SNP pairs by physical distance (e.g. 10-kb bins out to 500 kb) and average r² per bin; plot all populations' decay curves on shared axes. PopLDdecay produces the same plot directly and is a good cross-check.

### FST

Pairwise, windowed (classic route):

```bash
vcftools --gzvcf cohort.vcf.gz \
  --weir-fst-pop pop1.txt --weir-fst-pop pop2.txt \
  --fst-window-size 100000 --fst-window-step 50000 \
  --out OUTDIR/fst_pop1_pop2
```

Genome-wide multi-population (modern route):

```bash
plink2 --bfile OUTDIR/unrelated --fst --within popmap3.txt --out OUTDIR/fst
```

(`popmap3.txt` is the 3-column `FID IID POP` within-file. plink2's default FST is the Hudson estimator; `--fst method=wc` gives Weir–Cockerham.)

## Parameter decision rules

- **ROH parameters are density-dependent.** The defaults above suit SNP-array-scale human data (~500k SNPs). For denser WGS panels raise `--homozyg-snp` and `--homozyg-kb` (e.g. 100 SNP / 1000 kb) so that short, ancient background homozygosity is not called as ROH. State the parameters used when reporting F_ROH — values are comparable only within the same settings.
- **Long vs short ROH**: long segments (≥ 1–2 Mb) signal recent inbreeding; many short segments signal old background relatedness/small long-term Ne. Report both the length spectrum and the total.
- **LD decay**: use `--ld-window-r2 0.0` to keep all pairs (the default 0.2 truncates the informative tail). Each population needs ≥ ~20 individuals for stable r² averages.
- **FST**: treat small negative estimates as 0. Use windowed scans for outlier detection; use the genome-wide mean for population comparison. FST from the LD-pruned structure set and the full unrelated set should agree qualitatively — report which set was used.

## Output verification checklist

- `roh_segments.hom` (segments), `.hom.indiv` (per-sample sums) exist and are non-empty; every sample appears in `.hom.indiv` (zero-ROH samples included).
- `heterozygosity_stats.het` has one row per sample.
- `POP_ld.ld` has millions of rows for typical panels; spot-check that distances span 0–500 kb.
- FST outputs: `.weir.fst` (per-SNP) / `.windowed.weir.fst` (windows) from vcftools; `.fst` / `.fst.summary` from plink2.

## Figure reading guide

- **F_ROH per population (boxplot or bar)**: higher = more inbreeding. A population with wide spread has mixed histories within the group.
- **ROH count vs total length scatter** (one point per individual): points up-and-right with long segments = recent inbreeding; many segments but short total = ancient small Ne.
- **Observed heterozygosity per population**: lower = more drift/lower Ne. Compare against F sign, not just the rate.
- **LD decay curves**: faster decay = larger long-term Ne. A curve sitting above the others at all distances = smaller Ne or a recent bottleneck. Curves that fail to approach baseline by 500 kb suggest strong recent structure or few samples.

## Common pitfalls

- Computing ROH or heterozygosity before removing relatives — relatedness inflates both.
- Comparing F_ROH across datasets filtered with different `--homozyg-*` settings.
- LD decay on fewer than ~15–20 individuals per population: r² averages become sample-noise.
- Interpreting mean FST without noting ascertainment: SNP-array panels (pre-selected common SNPs) bias FST downward relative to WGS.
````

- [ ] **Step 2: Check for leftover placeholders**

Run: `grep -nE "TBD|TODO|FIXME" bioinformatics/population-genomics/references/diversity-statistics.md`
Expected: no output (exit 1).

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/population-genomics/references/diversity-statistics.md
git commit -m "Add diversity-statistics reference for population-genomics skill"
```

---

### Task 4: Create `references/population-structure.md`

**Files:**
- Create: `bioinformatics/population-genomics/references/population-structure.md`

- [ ] **Step 1: Write the file with exactly this content**

````markdown
# Population Structure: PCA and ADMIXTURE

PCA and ADMIXTURE are the two workhorse views of population structure. Their shared assumption — unlinked SNPs in unrelated individuals — is why they consume the strict round-2 LD-pruned set (`ld_pruned2`). Violating that assumption does not error out; it manufactures clusters and ancestry components that are not there.

## When to use

Read this when the task involves PCA (smartpca, EIGENSTRAT, `.evec`), ancestry estimation (ADMIXTURE, `.Q` files, choosing K), or interpreting structure plots.

## Command templates

### smartpca (EIGENSOFT)

1. Convert PLINK → PED (1/2-coded):

```bash
plink --bfile OUTDIR/ld_pruned2 --recode 12 --out OUTDIR/pca_temp
```

2. Write `OUTDIR/par.convertf` (convertf derives the `.ind` from the PED):

```text
genotypename:    OUTDIR/pca_temp.ped
snpname:         OUTDIR/pca_temp.map
indivname:       OUTDIR/pca_temp.ped
outputformat:    EIGENSTRAT
genotypeoutname: OUTDIR/pca.geno
snpoutname:      OUTDIR/pca.snp
indivoutname:    OUTDIR/pca.ind
```

Run `convertf -p OUTDIR/par.convertf`.

3. Write `OUTDIR/par.smartpca`:

```text
genotypename:   OUTDIR/pca.geno
snpname:        OUTDIR/pca.snp
indivname:      OUTDIR/pca.ind
evecoutname:    OUTDIR/pca_results.evec
evaloutname:    OUTDIR/pca_results.eval
numoutevec:     20
numoutlieriter: 5
altnormstyle:   YES
```

4. Run:

```bash
smartpca -p OUTDIR/par.smartpca > OUTDIR/smartpca.log 2>&1
```

Quick alternative when EIGENSOFT is unavailable: `plink2 --bfile OUTDIR/ld_pruned2 --pca 20 --out OUTDIR/pca` produces `.eigenvec`/`.eigenval` — fine for exploration, but smartpca adds Tracy–Widom significance and iterative outlier removal.

### ADMIXTURE

```bash
cd OUTDIR   # ADMIXTURE writes .Q/.P into the CURRENT directory, named after the input basename
for K in 2 3 4 5 6 7 8 9 10 11 12; do
  admixture --cv -s 42 -j4 ld_pruned2.bed $K > admixture_k${K}.log 2>&1
  mv ld_pruned2.${K}.Q admixture_k${K}.Q
  mv ld_pruned2.${K}.P admixture_k${K}.P
done
grep -h "CV error" admixture_k*.log > cv_errors.txt
```

## Parameter decision rules

- **smartpca**: `numoutevec: 20` covers any realistic structure; `numoutlieriter: 5` removes PCs driven by a handful of outliers (set to 0 only if the user asks to keep outliers); `altnormstyle: YES` is the recommended normalization for EIGENSOFT ≥ 6.
- **Choosing K**: pick the K with the lowest CV error — then still look at the neighbors. CV frequently declines monotonically on large datasets; in that case report the elbow plus one K below/above, and prefer the K whose components are biologically interpretable. Present the CV table to the user and decide together.
- **K sweep cost**: K values are independent runs — run them concurrently (or with `-j` threads each) rather than serially on large panels.
- **Reproducibility**: fix `-s 42` (default seeds from the clock).

## Output verification checklist

- `pca_results.eval` has 20 eigenvalues; `pca_results.evec` has samples+1 lines (first line = eigenvalues; then one line per sample: ID, eigenvector entries, population label last).
- `smartpca.log` ends normally and lists Tracy–Widom statistics — count how many PCs are significant (p < 0.05); that bounds how many PCs to plot and discuss.
- For every K: `admixture_k${K}.Q` line count = `ld_pruned2.fam` line count, and each row sums to ≈ 1.
- `cv_errors.txt` has one line per K.

## Figure reading guide

- **PCA biplot (PC1 vs PC2, colored by population)**: check variance explained per PC from `.eval` first — if PC1+PC2 explain < a few percent, structure is weak or homogeneous and over-interpretation is the main risk. Tight clusters matching known groups = discrete structure; gradients = isolation-by-distance; isolated single points = recent admixture, batch effects, or missed relatives (go back to the kinship step before believing them).
- **Ancestry bar plot (stacked `.Q`, samples grouped by population)**: read at the agreed K. Solid blocks = discrete ancestry; systematically mixed bars across a whole population = shared admixture history or gene flow; a component carried by one or two individuals = likely artifact of small sample size, not a "ghost population".
- Cross-check PCA and ADMIXTURE against each other: clusters on PCA should roughly correspond to dominant components. Disagreement usually means LD/relatedness leaked into the input set.

## Common pitfalls

- Running PCA/ADMIXTURE on `filtered` or `ld_pruned1` instead of `ld_pruned2` — unlinked-markers assumption broken, spurious clusters.
- ADMIXTURE's silent cwd behavior: `.Q`/`.P` appear next to where you ran it, named `<basename>.<K>.Q` — the `cd OUTDIR` + `mv` pattern above is deliberate.
- `.Q` rows are in `.fam` order — align samples to populations via the `.fam`, never by guesswork.
- Reporting only the CV-minimal K without inspecting bar plots: the statistical optimum and the interpretable answer often differ by ±1–2 K.
- Editing population labels: the third column of the `.ind` file carries the label used for plotting/outlier logic — set it from the population map rather than leaving all samples as `U`.
````

- [ ] **Step 2: Check for leftover placeholders**

Run: `grep -nE "TBD|TODO|FIXME" bioinformatics/population-genomics/references/population-structure.md`
Expected: no output (exit 1).

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/population-genomics/references/population-structure.md
git commit -m "Add population-structure reference for population-genomics skill"
```

---

### Task 5: Create `references/treemix-and-fstatistics.md`

**Files:**
- Create: `bioinformatics/population-genomics/references/treemix-and-fstatistics.md`

- [ ] **Step 1: Write the file with exactly this content**

````markdown
# TreeMix and f-Statistics

TreeMix builds a maximum-likelihood population tree and adds migration edges to explain residual covariance; f3/f4/D-statistics are formal hypothesis tests for admixture and gene flow. Both work from population allele frequencies on the same SNP panel, so they share input preparation — and both are only as meaningful as the population labels and outgroup choice.

## When to use

Read this when the task involves TreeMix (population trees, migration edges, `.treeout`), f3/f4/D-statistics (ADMIXTOOLS, qpAdm, qpGraph), or testing for gene flow between populations.

## Command templates

### TreeMix input preparation

TreeMix consumes per-population allele counts. Get them from PLINK stratified frequencies:

```bash
# popmap3.txt: 3-column within-file  FID IID POP
plink --bfile OUTDIR/ld_pruned2 --freq --within OUTDIR/popmap3.txt --out OUTDIR/treemix_in
```

Then convert `.frq.strat` to TreeMix format with `plink2treemix.py` (a widely-mirrored script from the Pickrell lab; fetch it from any reputable popgen toolbox repo, verify it reads `.frq.strat[.gz]`, or write the ~15-line conversion yourself from the spec below):

```bash
python plink2treemix.py OUTDIR/treemix_in.frq.strat.gz OUTDIR/treemix.frq.gz
```

**TreeMix input format spec** (self-sufficiency fallback): first line = population names separated by spaces; then one line per SNP, with one `count1,count2` pair per population in the same order — allele counts of the two alleles in that population.

### TreeMix runs

```bash
for m in 0 1 2 3 4 5; do
  treemix -i OUTDIR/treemix.frq.gz -m $m -o OUTDIR/treemix_m${m} \
    -root OUTGROUP -k 10000 -noss > OUTDIR/treemix_m${m}.log 2>&1
done
```

Plot with the official `plotting_funcs.R` (ships with TreeMix):

```r
source("plotting_funcs.R")
pdf("treemix_m2.pdf", width=10, height=6)
plot_tree("OUTDIR/treemix_m2")
plot_resid("OUTDIR/treemix_m2", "OUTDIR/pop_order.txt")  # pop_order.txt: one population per line, tree order
dev.off()
```

### f3 / f4 / D with the ADMIXTOOLS R package

ADMIXTOOLS reads an EIGENSTRAT prefix (`.geno/.snp/.ind` — reuse the smartpca conversion from population-structure) or, in current versions, a PLINK prefix; confirm against `help(f3)` in the installed version, as the API has shifted across releases.

```r
library(admixtools)
prefix <- "OUTDIR/pca"   # pca.geno / pca.snp / pca.ind

# f3 admixture test: is TARGET admixed from sources related to SRC1 and SRC2?
f3(prefix, "TARGET", "SRC1", "SRC2")

# f4 / D: do (POPA,POPB) and (POPC,POPD) form clades, or is there gene flow?
f4(prefix, "POPA", "POPB", "POPC", "POPD", f4mode = FALSE)   # f4mode=FALSE → D-statistic
```

Population names must match the `.ind`/`.fam` labels exactly — list them first (`read_ind` / the third `.ind` column) and build test triples/quadruples from the actual labels.

## Parameter decision rules

- **Rooting (`-root`)**: use a population known a priori to be an outgroup (YRI in worldwide human panels; an archaic or sister species where available). If no defensible outgroup exists, run unrooted and say so in the interpretation.
- **Block size (`-k`)**: SNPs per jackknife block; must span more than the LD extent. 10000 suits SNP-panel densities; for dense WGS 500–1000 is acceptable. `-noss` skips a sanity check that aborts runs on small/irregular datasets.
- **Choosing m**: collect each run's final log-likelihood (run log / `.llik`) and plot likelihood vs m. Take the elbow/plateau — formalized by OptM (pick the m explaining ≥ ~99.8% of variance). Then inspect residuals (`plot_resid`): large residual covariance between a pair means the graph still mis-models them; an m whose migration arrows sit on top of large residuals is underfit, one with arrows but no residuals is overfit. Present the likelihood table to the user.
- **Node support**: for bootstrap, generate block-bootstrap replicates (`-bootstrap`), rerun the chosen m, and summarize with a consensus tree; report support on key splits.
- **f3 interpretation**: f3(TARGET; SRC1, SRC2) significantly **negative** (Z < −3) supports TARGET being admixed between the source lineages. Non-negative f3 does not prove no admixture (power limits).
- **f4/D interpretation**: |Z| > 3 = significant. D ≠ 0 (e.g. D(A,B;C,OUT)) means excess allele sharing between one side and C — i.e. gene flow; the sign tells the direction. f4 ≈ 0 is consistent with tree-like relationships.
- **qpAdm/qpGraph (brief)**: qpAdm tests whether a target can be modeled as a mixture of the proposed sources given outgroups (p > 0.05 = model not rejected — test several source sets, not one); qpGraph fits an explicit admixture graph by f4 residuals (worst |Z| ≲ 3 = acceptable fit). Both need careful outgroup sets — consult the ADMIXTOOLS documentation before running.

## Output verification checklist

- `treemix.frq.gz` line count = SNP count + 1 (header); population count in header = populations in `popmap3.txt`.
- Per m: `treemix_m${m}.{treeout,vertices,edges,cov,covse}` exist; the log shows likelihood convergence.
- Likelihood extracted for every m before choosing (never pick m by habit).
- f3/f4 output tables contain estimate, standard error, and Z — report all three.

## Figure reading guide

- **TreeMix tree**: topology = drift history (splits ≈ divergences); branch length ≈ drift amount. Migration arrows: direction = source → recipient of gene flow; color/width = migration weight. Read arrows together with residuals, never alone.
- **Residual heatmap**: bright spots = population pairs whose covariance the graph fails to explain — candidate gene-flow events.
- **f3/f4 bar charts with error bars**: a result is only as strong as its Z; plot Z alongside the estimate.

## Common pitfalls

- Population-label mismatches between `.fam`, `popmap3.txt`, and the R calls — silent subsetting or wrong tests.
- Interpreting migration edges without checking residuals or trying the next m up.
- Comparing D-statistics computed on different SNP sets or different ascertainment panels.
- TreeMix on populations of 1–2 individuals: allele-count noise dominates; treat resulting trees as exploratory.
````

- [ ] **Step 2: Check for leftover placeholders**

Run: `grep -nE "TBD|TODO|FIXME" bioinformatics/population-genomics/references/treemix-and-fstatistics.md`
Expected: no output (exit 1).

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/population-genomics/references/treemix-and-fstatistics.md
git commit -m "Add treemix-and-fstatistics reference for population-genomics skill"
```

---

### Task 6: Create `references/demographic-inference.md`

**Files:**
- Create: `bioinformatics/population-genomics/references/demographic-inference.md`

- [ ] **Step 1: Write the file with exactly this content**

````markdown
# Demographic Inference: easySFS, fastsimcoal2, Demes

Site-frequency-spectrum (SFS) methods infer population sizes, divergence times, and migration from the joint allele-frequency distribution. fastsimcoal2 is powerful but famously unforgiving: malformed `.tpl`/`.est` files do not error — they hang forever or segfault. The rules below exist because each one has burned an analyst before; follow them exactly.

## When to use

Read this when the task involves the site frequency spectrum (SFS), easySFS, fastsimcoal2/fsc28 (`.tpl`, `.est`, `.obs`), demographic models (bottleneck, expansion, divergence, migration), or exporting models to Demes.

## Command templates

### 1. Build the SFS with easySFS

Population file: two whitespace-separated columns `sample_id population`.

```bash
python easySFS.py -i cohort.vcf.gz -p pops.txt --preview          # inspect projections & SNP yield
python easySFS.py -i cohort.vcf.gz -p pops.txt --proj 20,20,20 -o OUTDIR/sfs -f
```

Outputs: `dadi/*.sfs` and `fastsimcoal2/` — `POP_MSFS.obs` (multi-pop) or `POP1_jointMAFpop1_0.obs` (2-pop marginal). easySFS is not vendored here — install from its author repo (isaacovercast/easySFS).

### 2. Run fastsimcoal2

fsc28 locates the observed SFS **by the .tpl basename**: `PREFIX_MSFS.obs` (multi-pop) or `PREFIX_jointMAFpop1_0.obs` must sit in the run directory.

```bash
cd OUTDIR/run
cp ../sfs/fastsimcoal2/PREFIX_MSFS.obs .
fsc28 -t PREFIX.tpl -e PREFIX.est -m -M -n100000 -L40 -c12 -q > PREFIX.log 2>&1
```

- `-m` = folded (MAF) SFS — matches easySFS's default folded output; `-d` is for unfolded/polarized spectra.
- `-M` = likelihood maximization; `-n` simulations per evaluation (100000); `-L` optimization cycles (40); `-c` threads.
- One run is one point estimate: repeat with different seeds (≥ 10 exploratory, 40–100 for production) and keep the best-likelihood replicate.

### 3. Minimal working `.tpl` (2-pop divergence, constant sizes)

```text
//Number of population samples (demes)
2
//Population effective sizes (number of genes)
NPOP0
NPOP1
//Sample sizes (numbers of gene copies)
20
20
//Growth rates: negative growth = expansion backward in time
0
0
//Number of migration matrices
1
//Migration matrix 0
0 MIG
MIG 0
//Historical events: time, source, sink, migrants, new size, new growth, migr matrix
1 historical event
TDIV 0 1 1 RESIZE 0 0
//Number of independent loci [chromosomes]
1 0
//Per chromosome: data type, number of loci, recombination rate, mutation rate
FREQ 1 0 2.5e-8 OUTEXP
```

The historical-event line `TDIV 0 1 1 RESIZE 0 0` reads backward in time: at generation TDIV, 100% of pop 0 merges into pop 1 (= a forward-time divergence), and the sink is resized by factor RESIZE.

### 4. Matching `.est`

```text
// Priors and rules file

[PARAMETERS]
//#isInt? #name  #dist.    #min  #max
//all N are in numbers of haploid individuals
1  NPOP0  logunif  100   100000  output
1  NPOP1  logunif  100   100000  output
1  ANC    logunif  100   100000  output
0  TDIV   unif     2000  6000    output
0  MIG    logunif  1e-5  5e-4    output

[COMPLEX PARAMETERS]
0  RESIZE = ANC / NPOP1  hide
```

## Parameter decision rules

**easySFS projection** (per population): choose the largest even number ≤ (2 × individuals − 2), clipped to [2, 70]. Always `--preview` first: projection trades samples for SNPs — if the retained-SNP count collapses at your projection, lower it. Populations with few individuals cap the joint projection.

**fastsimcoal2 anti-hang / anti-crash rules (non-negotiable):**

1. Time flows backward in coalescent models: expansion times (TEXP) must be **smaller** than every divergence time (TDIV). TEXP > any TDIV = infinite hang.
2. All time ranges must be non-overlapping; keep them realistic (e.g. TEXP 800–1400, TDIV 2000–6000 for recent human-scale history).
3. No time values > 10,000 generations — known to segfault fsc28.
4. Migration rates: `logunif 1e-5 5e-4`, never above 0.01.
5. Parameter names must never be substrings of each other (`NANC` vs `NANC12` silently corrupts substitution). Use clearly distinct names: `NPOP0`, `ANC`, `TDIV12`. Common convention: current populations plain, ancestral sizes `ANC*`.
6. `[COMPLEX PARAMETERS]` comes after `[PARAMETERS]`; dummy/derived parameters are declared like `0 NAME unif 0 0 hide`.
7. No `[RULES]` section for fsc28.
8. Verify the final grammar against the fsc28 PDF manual of the installed version when in doubt — the parser is unforgiving.

**Single-population prior-setting from SFS summaries** (data-driven ranges):

- Estimate Ne ≈ π / (4 × 2.5e-8); set its range to [max(1000, 0.1·Ne), min(100000, 10·Ne)].
- From the Tajima's-D-like signal of the SFS:

| Signal | Interpretation | TEXP range | RESIZE range |
|---|---|---|---|
| D < −1.5 | recent rapid expansion | 50–5000 | 2.0–50.0 |
| −1.5 … −0.5 | moderate expansion | 100–10000 | 1.5–20.0 |
| D > 1.0 | bottleneck / balancing selection | 500–20000 | 0.1–2.0 |
| otherwise | roughly stable | 200–15000 | 0.5–5.0 |

**Likelihood-driven model search** (iterate, don't one-shot):

- Best likelihood still poor for the panel scale (e.g. > −30000): try a **simpler** model.
- Improvement between rounds < ~500 log units: make **more dramatic** parameter changes.
- MLE sits on a range boundary: **expand the range** in that direction and rerun.
- Compare candidate models by AIC = 2k − 2·lnL (k = estimated parameters), from each model's best replicate.

## Output verification checklist

- Per replicate: `PREFIX/PREFIX.bestlhoods` (likelihoods: MaxEstLhood vs MaxObsLhood — a large gap means the model fits poorly) and `PREFIX/PREFIX.maxlhood` (MLE parameter values).
- No MLE value pinned on a prior boundary (if so, see search rules).
- The `.obs` file matched the expected basename (fsc28 hangs or exits immediately otherwise) — remove it from the run directory afterward to keep runs isolated.
- All replicates used identical `.tpl/.est`; only seeds differ.

## Figure reading guide

- Plot the observed vs expected SFS from the best run (`PREFIX_bestYobs`-style outputs in the run directory): systematic residuals at rare or common bins point at model misfit.
- For the final model, export to Demes (below) and draw the demographic graph with `demesdraw` (Python) — a model diagram communicates sizes/times better than a parameter table.

## Demes export

Convert the MLE point estimates into a Demes YAML for sharing and downstream reuse (demes-spec format; validate with the `demes` Python package):

```yaml
description: Two-population divergence inferred with fastsimcoal2
time_units: generations
demes:
  - name: ANC
    epochs:
      - {end_time: TDIV_EST, start_size: ANC_EST}
  - name: POP0
    ancestors: [ANC]
    epochs:
      - {end_time: 0, start_size: NPOP0_EST}
  - name: POP1
    ancestors: [ANC]
    epochs:
      - {end_time: 0, start_size: NPOP1_EST}
migrations:
  - {demes: [POP0, POP1], rate: MIG_EST}
```

## Common pitfalls

- TEXP > TDIV, overlapping time ranges, or times > 10,000 generations → hang/segfault (rules 1–3).
- Substring parameter names (rule 5) → silent mis-substitution; results look fine but are wrong.
- Folded/unfolded mismatch: `-m` (MAF) with a folded easySFS spectrum vs `-d` with polarized data — mixing them invalidates everything.
- Reporting the first run as the answer instead of the best of many replicates.
- Projecting the SFS so aggressively that only a few hundred SNPs remain → jittery likelihoods and unstable MLEs.
````

- [ ] **Step 2: Check for leftover placeholders**

Run: `grep -nE "TBD|TODO|FIXME" bioinformatics/population-genomics/references/demographic-inference.md`
Expected: no output (exit 1).

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/population-genomics/references/demographic-inference.md
git commit -m "Add demographic-inference reference for population-genomics skill"
```

---

### Task 7: Register the skill (marketplace.json + README.md)

**Files:**
- Modify: `.claude-plugin/marketplace.json:17` (bioinformatics plugin `skills` array)
- Modify: `README.md:7-11` (bioinformatics section), `README.md:31-34` (install block)

- [ ] **Step 1: Add the skill to the bioinformatics plugin in `.claude-plugin/marketplace.json`**

Replace:

```json
    {
      "name": "bioinformatics",
      "description": "Skills for bioinformatics and computational biology workflows (NGS, single-cell, sequence analysis)",
      "source": "./",
      "strict": false,
      "skills": []
    },
```

with:

```json
    {
      "name": "bioinformatics",
      "description": "Skills for bioinformatics and computational biology workflows (population genomics, NGS, single-cell, sequence analysis)",
      "source": "./",
      "strict": false,
      "skills": [
        "./bioinformatics/population-genomics"
      ]
    },
```

- [ ] **Step 2: Validate the JSON**

Run: `python3 -m json.tool .claude-plugin/marketplace.json > /dev/null && echo VALID`
Expected: `VALID`

- [ ] **Step 3: Update the bioinformatics section in `README.md`**

Replace:

```markdown
### bioinformatics

Skills for bioinformatics and computational biology workflows (NGS, single-cell, sequence analysis, ...).

*No skills yet — contributions welcome.*
```

with:

```markdown
### bioinformatics

Skills for bioinformatics and computational biology workflows (population genomics, NGS, single-cell, sequence analysis, ...).

| Skill | Description |
|-------|-------------|
| [population-genomics](bioinformatics/population-genomics/) | Population-genomics analysis workflows — QC, LD pruning, kinship, PCA, ADMIXTURE, TreeMix, f-statistics, and fastsimcoal2 demographic inference from VCF/PLINK data |
```

- [ ] **Step 4: Add the bioinformatics install line in `README.md`**

Replace:

```markdown
```
/plugin marketplace add <your-github-user>/my-scientific-skills
/plugin install data-science@my-scientific-skills
```
```

with:

```markdown
```
/plugin marketplace add <your-github-user>/my-scientific-skills
/plugin install bioinformatics@my-scientific-skills
/plugin install data-science@my-scientific-skills
```
```

- [ ] **Step 5: Commit**

```bash
git add .claude-plugin/marketplace.json README.md
git commit -m "Register population-genomics skill in marketplace and README"
```

---

### Task 8: Final verification and trigger test

**Files:**
- Verify: `bioinformatics/population-genomics/` (all files)
- Verify: `README.md`, `.claude-plugin/marketplace.json`

- [ ] **Step 1: Run the repo's skill-size check**

Run: `./count-skill-tokens.py bioinformatics/population-genomics`
Expected: no `⚠️` on description or SKILL.md. All 6 files listed (SKILL.md + 5 references). If any warning appears, trim the flagged file and re-run.

- [ ] **Step 2: Verify SKILL.md ↔ references cross-references**

Run:

```bash
cd bioinformatics/population-genomics && \
grep -o 'references/[a-z-]*\.md' SKILL.md | sort -u && \
echo "---" && find references -name '*.md' | sort
```

Expected: the two lists match exactly (5 files).

- [ ] **Step 3: Install locally for the trigger test**

```bash
mkdir -p ~/.claude/skills
cp -r bioinformatics/population-genomics ~/.claude/skills/
```

- [ ] **Step 4: Trigger test (manual, in a NEW Claude Code session)**

Positive prompts (skill SHOULD trigger, and the agent should load only the relevant reference):
- "帮我分析这个 VCF 文件里样本的群体结构" → triggers; reads preprocessing-and-qc + population-structure
- "Run ADMIXTURE on my PLINK files and help me pick K" → triggers; reads population-structure
- "How do I test for gene flow between these populations?" → triggers; reads treemix-and-fstatistics

Negative prompts (skill should NOT trigger):
- "帮我质控一下 RNA-seq 的 FASTQ 数据"
- "Annotate cell types in my single-cell dataset"

If the skill misfires or fails to trigger, adjust the `description` (trigger phrases first), reinstall, and retest. If an agent cannot find a specific command in a reference, that is a reference gap — fix the reference.

- [ ] **Step 5: Commit any fixes from testing**

```bash
git add bioinformatics/population-genomics
git commit -m "Refine population-genomics skill after trigger testing"
```

(Omit if testing produced no changes.)
