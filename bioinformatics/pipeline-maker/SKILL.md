---
name: pipeline-maker
description: Build a modular Snakemake workflow from ad-hoc bash, a Jupyter notebook, or a described goal; or recover a misbehaving run (rerun storms, "Code has changed", ProtectedOutputException, incomplete files). Triggers on "Snakemake workflow", "write a Snakefile", "Snakemake reruns everything", or "pipeline-maker". Validates with `snakemake -n` in a fix loop. Not for Nextflow/WDL.
metadata:
  author: Altair Wei
  version: "1.0"
license: MIT
---

# Pipeline Maker

Build or recover a reproducible, modular Snakemake workflow — from ad-hoc bash commands, a Jupyter notebook, a described analysis goal, or a run that has gone sideways. Output is the modular layout (`Snakefile` + `config.yaml` + `workflow/rules/*.smk` + `common.smk` + `scripts/` + optional `workflow/envs/` + optional `profiles/`). Project-level layout (`experiments/`, `runall`, `lab-notebook.md`, `artifacts/`) is the `bioinfo-project-organization` skill's job — cross-reference it, do not duplicate.

## Working discipline

These habits separate a reliable workflow from a plausible-looking one. Follow them for every task.

### Generation

- **Confirm entry mode and input shape before generating.** Is the input bash history, a notebook file, prose-described steps, or a goal + data manifest? Ask if unclear — every downstream choice depends on it.
- **Plan first, then track.** Turn the goal into an explicit rule list / DAG and confirm it with the user (use the task list) before writing code. The workflow maps below are the menu; the user's question decides the selection.
- **Generate rule-by-rule or in small auditable batches.** Never dump an unverified Snakefile. Each rule should be checkable on its own.
- **Ground directives, don't recall them.** When unsure of a flag or helper, run `snakemake --help` or check the installed version's source before writing the command. Memory of tool flags drifts; the binary does not lie.
- **Decide judgment calls together.** Wildcard generalization scope, rule-vs-script splits, conda granularity — present options and let the user pick.
- **Defer project-level layout** to `bioinfo-project-organization`.

### Validation

- **Run the dry-run loop after every generation/edit.** Run `scripts/validate-workflow.py` (which runs `snakemake -n --cores 1`), read the real stderr, fix, retry. After 2–3 failed fixes on the same error, stop and report the diagnosis — do not loop silently.
- **Locate the failed job's log before guessing.** Check in order: the rule's `log:` file (never deleted on failure) → the main `.snakemake/log/` process log → the executor-plugin (SLURM) job logs. See `references/debugging.md`.
- **Never declare done until `snakemake -n` passes** (or, with the static fallback, the output is explicitly flagged "unvalidated").

### Recovery (the high-frequency mistakes)

- **Dry-run before any destructive or metadata-altering operation.** Before `--delete-temp-output`, `--delete-all-output`, `--cleanup-metadata`, or `--force`, run `--dry-run` first and read what it would touch.
- **Assess before editing a rule with completed outputs.** Editing a rule's shell text, a `params:` value, or a conda env retroactively invalidates prior outputs via the CODE/PARAMS/SOFTWARE trigger. Run `--list-changes` / `--list-input-changes` / `--list-params-changes` to see what would rerun; to keep valid outputs, `--cleanup-metadata` the **entire affected output subtree** (every rule output with a pre-change record), not just the obvious file.
- **After a force-stop, do not treat present files as complete.** Dry-run to enumerate `IncompleteFilesException` files (named in the exception), classify them as "to rebuild," then resume with `--rerun-incomplete` — do not delete their intermediates.
- **`temp()` reclaims disk but is not a rerun trigger and does not auto-delete prior-run intermediates.** Use `--delete-temp-output` (dry-run first). Mark shared outputs (e.g., an intervals BED used by all samples) as plain outputs, never `temp()`. Don't `temp()` outputs you might need to re-run downstream against — they're deleted once consumed.
- **When a tool reproducibly crashes on valid input, do not loop retries.** Substitute an equivalent and validate equivalence against the original before declaring success (e.g., vcftools → bcftools+awk, validated bin-by-bin).
- **Verify cohort assumptions before trusting pipeline defaults.** Ploidy (chrX/chrY diploid), MAF cutoffs, sample composition — verify with evidence (e.g., coverage-ratio sex check) and state the assumption.
- **Companion analysis scripts go in tracked `scripts/` or `experiments/`, never in gitignored `results/`.**

### Execution consent and feature grounding

- **Never launch a real pipeline run or a SLURM orchestrator without explicit user permission — default to `--dry-run`.** A dry-run is always safe; a real run is not. Unauthorized auto-runs have held directory locks for days and wasted cluster compute.
- **Confirm a Snakemake flag/helper exists in the installed version before using it.** `optional()` is not a built-in; `update()`/`branch()`/`--executor touch` need Snakemake 9+. `rg` the vendored source or `python -c "import snakemake"`, never assume from memory.

## Workflow map — Mode A (bash/notebook → workflow)

1. Collect the input (bash commands paste/file/history, or a notebook file).
2. Classify commands: important (contributes to the workflow) vs one-timer (skip). Ask the user on ambiguity.
3. For each important command: extract input/output files, infer a rule name, decide rule-vs-script.
4. Detect composite opportunities (merge commands into one rule) and wildcard generalization (same command over many files → wildcard rule). Present inferences; let the user confirm before generalizing across samples.
5. Build the dependency DAG (match outputs → inputs).
6. Generate rules from `assets/rule.tmpl` / `assets/workflow-rules.smk.tmpl`; write `Snakefile` (`assets/Snakefile.tmpl`), `config.yaml` (`assets/config.yaml.tmpl`), and `common.smk` (`assets/common.smk.tmpl`) when shared helpers are needed. Notebook path also writes `scripts/*.py` (prefix + suffix codegen).
7. Run `validate-workflow.py`; fix loop until dry-run passes.

The notebook sub-path (load `references/notebook-to-workflow.md`): resolve per-cell Read/Write/Wildcards variables → dependency DAG (Read matched to nearest prior Write) → decide Rule-vs-Script per cell with the cascading constraint (a Script depending on a Rule's output must become a Rule) → generate prefix code (imports, args, input reading) + suffix code (output writing) + Snakemake rules → export.

## Workflow map — Mode B (from-scratch → workflow)

1. Clarify the goal and the data manifest: inputs, samples table, reference, tools.
2. Decompose into steps; for each step name the tool, inputs, outputs, params.
3. Decide rule granularity and wildcard strategy; sketch the DAG; confirm with the user.
4. Generate the modular scaffold from assets and fill in the rules; optionally load `references/deployment.md` to add conda envs / a SLURM profile.
5. Run `validate-workflow.py`; fix loop.

## Workflow map — Recovery

When the user reports a rerun storm, `ProtectedOutputException`, incomplete files after a crash, or disk bloat:

1. Load `references/rerun-and-metadata.md`. Run `--list-changes` (or `--list-input-changes` / `--list-params-changes`) and/or a `--dry-run` to enumerate what is invalidated or incomplete.
2. Classify: stale-code (data-valid outputs judged "Code has changed") vs genuinely-incomplete (force-stopped) vs disk-bloat (reclaimable temp).
3. Propose the recovery command set (whole-subtree `--cleanup-metadata`, `--rerun-incomplete`, `--delete-temp-output` — always `--dry-run` first), confirm with the user, run, and verify no `ProtectedOutputException` remains and the dry-run is clean.

## Data contract

- **Inputs**: bash commands / notebook / prose steps / goal description; a samples TSV for multi-sample workflows; reference data paths.
- **Output layout**: `Snakefile` + `config.yaml` + `workflow/rules/*.smk` + `common.smk` (shared helpers) + `scripts/` + optional `workflow/envs/*.yaml` + optional `profiles/<env>/`. Project-level layout (`experiments/`, `runall`, `lab-notebook.md`, `artifacts/`) → `bioinfo-project-organization`.
- **Snakemake version**: target current stable (8.x/9.x). `snakemake -n` is the validation primitive.
- **Raw inputs are immutable**: filtering and conversion always write new files; never edit inputs in place.

## Validation loop (core)

After any rule generation/edit, run `scripts/validate-workflow.py` (which runs `snakemake -n --cores 1`). Read the output, locate the failing rule, fix, retry. If `snakemake` is absent, the script falls back to a static-structure check and clearly warns that real validation requires installing snakemake.

## References (load on demand)

Read these only when the current task reaches them. Each is self-contained.

- `references/bash-to-workflow.md` — Mode A with bash input.
- `references/notebook-to-workflow.md` — Mode A with a notebook.
- `references/snakemake-rules-and-best-practices.md` — writing or reviewing any rule's syntax.
- `references/modularization-and-config.md` — structuring the workflow into modules/config.
- `references/deployment.md` — environments, cluster/cloud, or when a job OOMs.
- `references/rerun-and-metadata.md` — any recovery task, or whenever editing an existing rule.
- `references/debugging.md` — when a dry-run fails and the cause is non-obvious.

## Rules

- Never claim a workflow works without a passing dry-run (or an explicitly flagged static-only check).
- Paste the real stderr in the conversation; do not paraphrase "it passed."
- Never copy snkmaker or snakemake source verbatim — write original guidance and cite docs by section.
- Present inferred wildcard generalizations and let the user confirm before generalizing across samples.
- New samples are added in `config.yaml`, never by editing the Snakefile.
