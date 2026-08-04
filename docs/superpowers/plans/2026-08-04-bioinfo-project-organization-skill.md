# `bioinfo-project-organization` Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `bioinformatics/bioinfo-project-organization` skill — a SKILL.md plus five drop-in asset templates — that teaches Claude to organize a computational-biology / scientific-research project for reproducibility per Noble (2009), then register it in the marketplace and README.

**Architecture:** Per the approved spec (`docs/superpowers/specs/2026-08-04-bioinfo-project-organization-design.md`): a single `SKILL.md` carries the tool-agnostic methodology (principles, directory organization, experiment rules, lab notebook, Git, large-output handling); `assets/` carries five templates Claude drops when scaffolding a new project (`lab-notebook.md`, `.gitignore`, `runall`, `experiments/README.md`, `artifacts/README.md`). No `references/` (content fits one file). No `scripts/` (Claude scaffolds directly).

**Tech Stack:** Markdown skill files (Claude Skills YAML frontmatter); Noble (2009), *A Quick Guide to Organizing a Computational Biology Project*, as the sole methodology source; `count-skill-tokens.py` for size verification; `.claude-plugin/marketplace.json` + `README.md` for registration.

**Source material:** All content below is original prose distilling Noble (2009). Executors do NOT need any external source — every file's complete content is embedded in this plan.

**Note on testing:** This plan authors markdown content (a skill + templates); there are no unit tests. The automated check is `./count-skill-tokens.py` for size limits (SKILL.md < 5000 tokens / 500 lines, description < 100 tokens); the behavioral check is a manual local trigger test documented in Task 4.

---

### Task 1: Create `SKILL.md`

**Files:**
- Create: `bioinformatics/bioinfo-project-organization/SKILL.md`

- [ ] **Step 1: Write `bioinformatics/bioinfo-project-organization/SKILL.md` with exactly this content**

`````markdown
---
name: bioinfo-project-organization
description: Guides Claude in organizing a computational biology or scientific research project for reproducibility — directory layout, per-experiment driver scripts, a chronological lab notebook, and Git practices. Use this skill whenever the user is starting, setting up, or restructuring a computational project, or asks to "organize the project", "set up a new project", "directory layout", "lab notebook", "make this reproducible", or "runall". Applies Noble (2009), A Quick Guide to Organizing a Computational Biology Project.
metadata:
  author: Altair Wei
  version: "1.0"
license: MIT
---

# Bioinformatics Project Organization

Organize a computational project so that a stranger — including your future self — can look at the files and understand in detail what you did and why. This is Noble (2009), *A Quick Guide to Organizing a Computational Biology Project* (PLoS Comput Biol), distilled into tool-agnostic rules. The point is reproducibility: everything you do, you will probably have to do over again, so organize so that repeating an experiment with new data or parameters is trivial.

## First: new project or existing?

- **New project** → scaffold the structure from `assets/` (below), then `git init` + first commit so the scaffold is itself a checkpoint.
- **Existing project** → read the current layout, run `git status`, and read `lab-notebook.md` (if any) before doing anything. Surface what's missing and fill gaps non-destructively. Never force-rearrange a project that already works.

## Core principles

1. **Reproducibility by a stranger.** Someone unfamiliar with the project must be able to reconstruct what you did and why from the files alone — no private notes, no memory.
2. **Murphy's law.** Assume you will redo every analysis. Organize so that rerunning with new data or parameters is a one-line change, not a rewrite.

## Directory organization

**Logical top, chronological bottom.** Organize the project root by *what* things are (data, code, manuscripts); organize experiments by *when* you did them. Never put date-named directories at the project root — a root full of `2024-03-12/`, `2024-03-15/` is as bad as no organization at all.

Choose a top-level layout that matches the work, and create directories on demand rather than up front:

- **Script-driven** (Python / R / Shell): `data/  scripts/  experiments/  doc/`
- **Notebook-driven** (Jupyter / Quarto / R Markdown): `data/  notebooks/  experiments/  doc/`
- **Compiled code** (C / Rust extensions): `data/  src/  bin/  build/  experiments/  doc/`

`data/` is recommended whenever there is data, but a methods, literature-review, or software-package project may legitimately have none. If `data/` exists, give it a `README.md` recording the dataset's source, license, and any preprocessing.

## Experiments

Every experiment lives in `experiments/YYYY-MM-DD[-description]/`. Inside each experiment directory:

1. A `runall` driver script records every command, in order, that produces the experiment's results. The whole experiment is reproducible by running `./runall`.
2. Driver scripts are **restartable**: wrap expensive steps in `if [ ! -f expected_output ]; then … fi` so reruns skip work already done.
3. **Never hand-edit intermediate files.** If an output needs a manual tweak to feed the next step, write the tweak as a script (sed / awk / Python) or fix the upstream script to produce the right thing. Hand edits are invisible and unreproducible.
4. Use **relative paths** (relative to the experiment directory) so the project is portable to another machine or location.
5. **Comment generously.** Someone should understand the workflow from the comments alone.
6. Put experiment outputs in `experiments/YYYY-MM-DD/results/`, not scattered at the project root.
7. Reusable code lives at the top level (`scripts/`, `notebooks/`), not buried inside an experiment directory. Experiment directories hold only that experiment's `runall` and results.

A `runall` skeleton and an `experiments/README.md` are in `assets/`.

## Lab notebook

`lab-notebook.md` at the project root is the chronological log of the project. After every experiment, append a dated entry:

```markdown
## YYYY-MM-DD

- **What:** …
- **Why:** …
- **Observed:** …
- **Conclusion:** …
- **Next:** …
```

Record failed experiments too, and *how you know they failed* — the interpretation of a negative result is often not obvious to a later reader. Link key outputs (paths to plots, tables, artifact files). Transcribe decisions and discussion points that came up in conversation, since those won't be visible in the code.

A template is in `assets/lab-notebook.md`.

## Git

Git tracks **how you computed** — scripts, notebooks, documentation, configuration. (Large outputs are handled separately, below.)

1. **Commit per logical unit of work.** One commit = one logical change. Don't batch unrelated changes; don't let a day's worth of edits pile up uncommitted.
2. **Tag milestones.** When an experiment is confirmed, `git tag YYYY-MM-DD-description` so that exact state is recoverable later.
3. **Start with `git status`.** Before new work, check what's modified or untracked.
4. **Configure `.gitignore`.** Exclude large files, environment directories, and build artifacts — a starter `.gitignore` is in `assets/`.
5. **Branch for risk.** Before modifying a verified `runall`, `git checkout -b experiment/new-param`; merge only after it reproduces.
6. **Commit messages and lab-notebook complement each other.** The commit message says *what* (concise); the lab-notebook entry says *why* and *what the result was* (detailed). Cross-reference them by date and artifact name.

## Large outputs

Git is for code, docs, and config. Large binaries — model weights, big result tables, intermediate bulk — do **not** belong in git; they bloat the repo and make it uncloneable.

Put large outputs in an `artifacts/` directory at the project root:

- `.gitignore` ignores the binary *contents* of `artifacts/` but **keeps** `artifacts/README.md` tracked.
- `artifacts/README.md` is a provenance log: for each artifact, record its name, source, the command that generated it, the date, and any notes. The bulk stays out of git, but the trail of what was produced and how is version-controlled.

Templates are in `assets/.gitignore` and `assets/artifacts/README.md`.

## When you scaffold a new project

1. Ask (or infer) the work type and pick a top-level pattern from the list above.
2. Create the chosen top-level directories plus `experiments/`.
3. Drop `assets/lab-notebook.md` at the root as `lab-notebook.md`.
4. Drop `assets/.gitignore` at the root as `.gitignore`.
5. Drop `assets/experiments/README.md` into `experiments/`.
6. Create `artifacts/` and drop `assets/artifacts/README.md` into it.
7. Copy `assets/runall` into each new experiment directory as you create it, and `chmod +x` it.
8. `git init` (if not already) → `git add -A` → `git commit -m "Initial project scaffold"`.

Adjust every dropped file to the project — they are starting points, not scripture.
`````

- [ ] **Step 2: Validate size**

Run from the repo root:
```bash
./count-skill-tokens.py bioinformatics/bioinfo-project-organization
```
Expected: no warnings — SKILL.md under 5000 tokens / 500 lines, description under 100 tokens. If the description exceeds 100 tokens, trim trigger phrases in the `description:` line (drop the `or "runall"` or shorten the opening clause) and rerun until it passes.

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/bioinfo-project-organization/SKILL.md
git commit -m "Add bioinfo-project-organization SKILL.md"
```

---

### Task 2: Create the asset templates

**Files:**
- Create: `bioinformatics/bioinfo-project-organization/assets/lab-notebook.md`
- Create: `bioinformatics/bioinfo-project-organization/assets/.gitignore`
- Create: `bioinformatics/bioinfo-project-organization/assets/runall`
- Create: `bioinformatics/bioinfo-project-organization/assets/experiments/README.md`
- Create: `bioinformatics/bioinfo-project-organization/assets/artifacts/README.md`

- [ ] **Step 1: Write `assets/lab-notebook.md` with exactly this content**

`````markdown
# Lab Notebook

Chronological log of the project. Append a new entry for every experiment —
failed ones too. Adapt the section headers to your project; the point is that
a stranger can read this and understand what was done, why, and what the
result was.

## 2026-08-04

- **What:** ran the motif scan over the curated FASTA set with the new
  background model.
- **Why:** the previous scan used a uniform background and over-called
  AT-rich regions; the new model corrects for genomic composition.
- **Observed:** 312 significant motifs (FDR < 0.05), down from 487 — the
  AT-rich false positives collapsed as expected. The top hit is still SOX2.
- **Conclusion:** the new background is an improvement; reuse it for
  downstream scans.
- **Next:** rerun the enrichment analysis against the filtered motif set;
  compare to the ChIP-seq peak overlap.
- **Failed:** none today. (When something fails, record *how you know* it
  failed — e.g. "all p-values were uniform, indicating the permutation test
  never ran on the shuffled control".)

<!-- Link key outputs:
     experiments/2026-08-04/results/top_motifs.tsv
     artifacts/model_newbg.h5 -->
`````

- [ ] **Step 2: Write `assets/.gitignore` with exactly this content**

`````text
# .gitignore for a computational biology / scientific research project.
# Edit to fit your project — this is a starting point, not scripture.

# --- Artifacts: track the provenance README, ignore the bulk -------------
artifacts/*
!artifacts/README.md

# --- Python -------------------------------------------------------------
__pycache__/
*.pyc
.venv/
venv/

# --- Conda / virtualenv directories -------------------------------------
envs/
.env/

# --- Large binary file types (keep these out of git) --------------------
# Common computational-biology bulk formats; add any you produce.
*.h5
*.pdb
# *.bam
# *.vcf
# *.hdf5

# --- Large result tables (uncomment if you keep raw results out of git) -
# results/
# *.parquet

# --- Jupyter ------------------------------------------------------------
.ipynb_checkpoints/

# --- OS cruft -----------------------------------------------------------
.DS_Store
Thumbs.db
`````

- [ ] **Step 3: Write `assets/runall` with exactly this content, then make it executable**

`````bash
#!/usr/bin/env bash
# runall — drive a single experiment. Every command that produces this
# experiment's results lives here, in order. Rerun this script to reproduce
# the experiment from scratch.
#
# Adapt the variables and steps below to your experiment. Keep the structure:
#   - all paths/files as variables at the top
#   - each expensive step restartable (skips work already done)
#   - relative paths (relative to this experiment directory)
#   - generous comments — someone should understand the workflow from these
set -euo pipefail

cd "$(dirname "$0")"   # run from the experiment directory, whatever the cwd

# --- Paths (edit these) -------------------------------------------------
DATA_DIR="../../data"          # project-level data
RESULTS_DIR="results"
mkdir -p "$RESULTS_DIR"

# --- Step 1: preprocess -------------------------------------------------
# Restartable: skip if the output already exists.
if [ ! -f "$RESULTS_DIR/clean.parquet" ]; then
  echo "[1/2] preprocessing..."
  # TODO: python ../../scripts/preprocess.py "$DATA_DIR/input.tsv" "$RESULTS_DIR/clean.parquet"
  :
fi

# --- Step 2: analyze ----------------------------------------------------
if [ ! -f "$RESULTS_DIR/scores.tsv" ]; then
  echo "[2/2] analyzing..."
  # TODO: python ../../scripts/analyze.py "$RESULTS_DIR/clean.parquet" "$RESULTS_DIR/scores.tsv"
  :
fi

echo "done. results in $RESULTS_DIR/"
`````

Then:
```bash
chmod +x bioinformatics/bioinfo-project-organization/assets/runall
```

- [ ] **Step 4: Write `assets/experiments/README.md` with exactly this content**

`````markdown
# Experiments

Each subdirectory here is one experiment, named by date (optionally with a
short slug):

    experiments/
    └── 2026-08-04-motif-scan/
        ├── runall          # every command, in order; rerun to reproduce
        └── results/        # this experiment's outputs

Rules:

- One `runall` per experiment. Rerunning `./runall` reproduces the whole
  experiment.
- Outputs go in `results/` under the experiment directory, not at the project
  root.
- Reusable code lives at the project top level (`scripts/`, `notebooks/`),
  not copied into each experiment. Experiment directories hold only that
  experiment's `runall` and results.
- Large outputs (model weights, big tables) go to the project-level
  `artifacts/` directory, not here — see `../artifacts/README.md`.
`````

- [ ] **Step 5: Write `assets/artifacts/README.md` with exactly this content**

`````markdown
# Artifacts

Large binary outputs — model weights, big result tables, intermediate bulk —
live here, **not** in git. The `.gitignore` at the project root ignores the
contents of this directory but tracks this README, so the provenance log stays
version-controlled even as the bulk comes and goes.

Record every artifact you produce:

| Artifact | Source | Generated by | Date | Notes |
|---|---|---|---|---|
| model_newbg.h5 | data/input.tsv | `experiments/2026-08-04/runall` | 2026-08-04 | new background model; see lab-notebook entry |
| top_motifs.tsv | model_newbg.h5 | `experiments/2026-08-04/runall` | 2026-08-04 | FDR < 0.05 |

Add a row whenever you create or regenerate an artifact. If an artifact is
regenerated with different parameters, bump a version in the filename
(`model_v2.h5`) and add a new row rather than overwriting silently.
`````

- [ ] **Step 6: Commit**

```bash
git add bioinformatics/bioinfo-project-organization/assets
git commit -m "Add asset templates for bioinfo-project-organization skill"
```

---

### Task 3: Register the skill in the marketplace and README

**Files:**
- Modify: `.claude-plugin/marketplace.json`
- Modify: `README.md`

- [ ] **Step 1: Add the skill to the `bioinformatics` plugin in `.claude-plugin/marketplace.json`**

The `bioinformatics` plugin's `skills` array currently reads:

```json
      "skills": [
        "./bioinformatics/population-genomics"
      ]
```

Change it to:

```json
      "skills": [
        "./bioinformatics/population-genomics",
        "./bioinformatics/bioinfo-project-organization"
      ]
```

(Make sure to add the comma after `"./bioinformatics/population-genomics"` so the JSON stays valid.)

- [ ] **Step 2: Add a row to the `bioinformatics` category table in `README.md`**

Immediately after the existing `population-genomics` row (the line beginning `| [population-genomics]`), add this row:

```markdown
| [bioinfo-project-organization](bioinformatics/bioinfo-project-organization/) | Organize a computational biology / scientific research project for reproducibility — Noble (2009) layout, per-experiment `runall`, a chronological `lab-notebook.md`, Git practices, and an `artifacts/` directory for large outputs |
```

- [ ] **Step 3: Verify the registration is consistent**

Run:
```bash
python -c "import json; json.load(open('.claude-plugin/marketplace.json'))" && echo "JSON valid"
ls bioinformatics/bioinfo-project-organization/
```
Expected: `JSON valid`, and the directory listing shows `SKILL.md` and `assets/`. The path in `marketplace.json` (`./bioinformatics/bioinfo-project-organization`) must match the directory exactly.

- [ ] **Step 4: Commit**

```bash
git add .claude-plugin/marketplace.json README.md
git commit -m "Register bioinfo-project-organization skill in marketplace and README"
```

---

### Task 4: Final validation and trigger-test documentation

**Files:** none modified unless the trigger test surfaces description edits.

- [ ] **Step 1: Re-run the size check end-to-end**

```bash
./count-skill-tokens.py bioinformatics/bioinfo-project-organization
```
Expected: no warnings. SKILL.md is under 5000 tokens / 500 lines; the description is under 100 tokens. This confirms the final registered skill is within repo limits.

- [ ] **Step 2: Manual local trigger test (run this checklist)**

This step is behavioral and must be run by a human (or an agent driving a fresh session). It cannot be automated inside this plan.

1. Copy the skill into the local skills directory:
   ```bash
   cp -r bioinformatics/bioinfo-project-organization ~/.claude/skills/
   ```
2. Start a **fresh** Claude Code session (so the skill is newly discovered).
3. Try these **positive** prompts — the skill should activate:
   - "Help me set up a new computational project for my analysis."
   - "Organize my analysis directory — I have scripts and data everywhere."
   - "Make this experiment reproducible; I want a lab notebook."
4. Try these **negative** prompts — the skill should **not** activate:
   - "Explain what this Python function does."
   - "QC my raw sequencing reads."
5. Record the results. If the skill fails to trigger on positive prompts or triggers on negative ones, the `description` needs tuning — edit the `description:` line in `SKILL.md`, re-run Step 1, and re-test.

- [ ] **Step 3: Commit any description tweaks (only if Step 2 surfaced them)**

If the trigger test required edits to the `description:` line:
```bash
git add bioinformatics/bioinfo-project-organization/SKILL.md
git commit -m "Tune bioinfo-project-organization description for reliable triggering"
```
If no edits were needed, skip this step — the skill is complete.
