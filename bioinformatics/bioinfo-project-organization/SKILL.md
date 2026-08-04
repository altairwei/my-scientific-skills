---
name: bioinfo-project-organization
description: Guides Claude in organizing a computational biology or scientific research project for reproducibility. Use this skill whenever the user is starting, setting up, or restructuring a computational project, or asks to "organize the project", "set up a new project", "directory layout", "lab notebook", "make this reproducible", or "runall". Applies Noble (2009), A Quick Guide to Organizing a Computational Biology Project.
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
