# `pipeline-maker` Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the `bioinformatics/pipeline-maker` skill — a SKILL.md plus seven reference files, five asset templates, and one validation script — that teaches Claude to build and recover modular Snakemake workflows, then register it in the marketplace and README.

**Architecture:** Per the approved spec (`docs/superpowers/specs/2026-08-04-pipeline-maker-design.md`): SKILL.md carries working discipline (generation + validation + recovery), two-and-a-half workflow maps (Mode A bash/notebook → workflow, Mode B from-scratch → workflow, Recovery), a data contract, the mandatory dry-run validation loop, and pointers to seven load-on-demand references. `references/*.md` carry per-topic methodology and command facts. `assets/` are drop-in skeletons. `scripts/validate-workflow.py` is the one deterministic helper. Project-level layout is deferred to `bioinfo-project-organization`.

**Tech Stack:** Markdown skill files (agentskills.io frontmatter spec); Snakemake 8.x/9.x (target current stable; rerun-trigger semantics verified in `external/snakemake/src/snakemake/persistence/__init__.py` + `settings/enums.py` + `cli.py`); Python 3 (`# /// script` inline deps, `uv run`) for the validator; `count-skill-tokens.py` for size verification; `marketplace.json` + `README.md` for registration.

**Testing note:** Per the user, no formal test harness — verification is (a) `./count-skill-tokens.py` size check, (b) accuracy spot-check against the cited snakemake docs/source, and (c) for the script, `py_compile` + a `--help` smoke. Real-world triggering/dry-run validation is done by the user.

**Source material:** Every concrete command, flag, and source-citation below is grounded in `external/snakemake/docs/snakefiles/{rules,debugging_workflows}.rst`, `external/snakemake/docs/executing/cli.rst`, `external/snakemake/src/snakemake/{persistence/__init__.py,settings/enums.py,cli.py}`, and the WGS session transcripts (`external/session_files/...-WGS-pipeline/`). Executors do NOT need to re-read those — every file's content is specified below.

---

### Task 1: Create `SKILL.md`

**Files:**
- Create: `bioinformatics/pipeline-maker/SKILL.md`

- [ ] **Step 1: Write `bioinformatics/pipeline-maker/SKILL.md` with exactly this content**

````markdown
---
name: pipeline-maker
description: Use when building or generating a Snakemake workflow (turn ad-hoc bash, a Jupyter notebook, or a described goal into a modular pipeline — Snakefile + config.yaml + workflow/rules/ + scripts/), or recovering a misbehaving Snakemake run (rerun storms, "Code has changed", ProtectedOutputException, incomplete files, temp/protected outputs). Triggers on "Snakemake workflow", "turn my bash into a pipeline", "convert this notebook to Snakemake", "write a Snakefile", "Snakemake reruns everything", or "pipeline-maker". Validates with `snakemake -n` and corrects in a loop. Not for Nextflow or WDL.
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
````

- [ ] **Step 2: Verify size and description**

Run: `./count-skill-tokens.py bioinformatics/pipeline-maker`
Expected: SKILL.md < 5000 tokens / 500 lines; `description` < 100 tokens. (Description above is ~95 tokens.)

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/pipeline-maker/SKILL.md
git commit -m "Add pipeline-maker SKILL.md"
```

---

### Task 2: Create the five asset templates

**Files:**
- Create: `bioinformatics/pipeline-maker/assets/Snakefile.tmpl`
- Create: `bioinformatics/pipeline-maker/assets/config.yaml.tmpl`
- Create: `bioinformatics/pipeline-maker/assets/rule.tmpl`
- Create: `bioinformatics/pipeline-maker/assets/workflow-rules.smk.tmpl`
- Create: `bioinformatics/pipeline-maker/assets/common.smk.tmpl`

- [ ] **Step 1: Write `assets/Snakefile.tmpl`**

````snakefile
# Main Snakefile entry — pipeline-maker asset.
# Load config, then include the modular rule files. Adapt the module/use-rule
# form per references/modularization-and-config.md if you prefer module isolation.
configfile: "config.yaml"

include: "workflow/rules/main.smk"
````

- [ ] **Step 2: Write `assets/config.yaml.tmpl`**

````yaml
# pipeline-maker asset — adapt to your project.
# Multi-sample: prefer a samples.tsv table and read it here via a thin loader.
samples:
  - sample_01
  - sample_02

paths:
  input_dir: data/
  output_dir: results/

params:
  threads: 4
  # Add tool-specific params here; reference them in rules via config[].
````

- [ ] **Step 3: Write `assets/rule.tmpl`**

````snakefile
# pipeline-maker asset — single-rule skeleton. Replace <NAME>, <INPUT>, <OUTPUT>,
# <WILDCARD>, <COMMAND>. Keep the log directive (survives failures for debugging).
rule <NAME>:
    input:
        <INPUT>
    output:
        <OUTPUT>
    log:
        "logs/{<WILDCARD>}/<NAME>.log"
    params:
        <PARAMS>
    shell:
        "<COMMAND> > {log} 2>&1"
````

- [ ] **Step 4: Write `assets/workflow-rules.smk.tmpl`**

````snakefile
# pipeline-maker asset — modular rule file with a wildcarded example showing the
# generalization pattern (one rule over many samples). Adapt the wildcard and
# the command.
rule <NAME>:
    input:
        "{sample}.fastq"
    output:
        "{sample}.bam"
    log:
        "logs/{sample}/<NAME>.log"
    shell:
        "tool {input} > {output} 2> {log}"
````

- [ ] **Step 5: Write `assets/common.smk.tmpl`**

````snakefile
# pipeline-maker asset — shared helper functions used across stage rule files.
# Rule-formatting helpers (string builders for shell args) belong here; pure
# analysis logic belongs in scripts/*.py, not here.

def get_log_path(wildcards, rule_name):
    """Standard log path per sample+rule. Called (not bare-ref) in rules."""
    return f"logs/{wildcards.sample}/{rule_name}.log"

# Example: a resource-arg builder (GATK --resource needs label+VCF paired).
# Adapt the pairing pattern to your tools.
# def get_resource_args(wildcards):
#     return " ".join(f"--resource:{label},key=... {path}" for label, path in RESOURCES)
````

- [ ] **Step 6: Verify the templates render as text and have placeholder tokens**

Run: `for f in Snakefile config.yaml rule workflow-rules.smk common.smk; do echo "== $f =="; head -3 bioinformatics/pipeline-maker/assets/$f.tmpl; done`
Expected: each prints its header comment; `rule.tmpl` and `workflow-rules.smk.tmpl` contain `<NAME>` / `{sample}`.

- [ ] **Step 7: Commit**

```bash
git add bioinformatics/pipeline-maker/assets/
git commit -m "Add pipeline-maker asset templates"
```

---

### Task 3: Create `scripts/validate-workflow.py`

**Files:**
- Create: `bioinformatics/pipeline-maker/scripts/validate-workflow.py`

- [ ] **Step 1: Write the script with exactly this content**

````python
#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
# pipeline-maker asset — deterministic validation helper.
# Runs `snakemake -n --cores 1` in the workflow directory, classifies the
# high-frequency Snakemake exceptions, prints the full stderr for Claude to
# read, and falls back to a static-structure check if snakemake is absent.
# It does NOT attempt fixes. Called by Claude inside the validation loop.

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Real high-frequency exceptions observed in the WGS session data.
CLASSIFY = [
    (re.compile(r"ProtectedOutputException"), "rerun-and-metadata.md",
     "a protected() output would be overwritten — likely the stale-code trap"),
    (re.compile(r"IncompleteFilesException"), "rerun-and-metadata.md",
     "files marked incomplete (force-stopped) — resume with --rerun-incomplete"),
    (re.compile(r"Code has changed"), "rerun-and-metadata.md",
     "a rule's shell text/params/conda env changed — cleanup-metadata the whole subtree"),
    (re.compile(r"MissingInputException"), "debugging.md",
     "no rule produces an input, or a wildcard resolves to nothing"),
    (re.compile(r"MissingOutputException"), "debugging.md",
     "a rule did not produce a declared output"),
    (re.compile(r"AmbiguousRuleException"), "debugging.md",
     "multiple rules can produce the same output — constrain wildcards or set ruleorder"),
    (re.compile(r"WildcardError"), "debugging.md",
     "unconstrained or ambiguous wildcard"),
    (re.compile(r"WorkflowError"), "debugging.md",
     "broad snakemake error — read the message"),
]

RULE_RE = re.compile(r"^\s*rule\s+(\w+)\s*:", re.MULTILINE)
OUTPUT_RE = re.compile(r"^\s*output:\s*(.*)$", re.MULTILINE)
SHELL_OR_RUN_RE = re.compile(r"^\s*(shell|run):\s*(.*)$", re.MULTILINE)


def run_dryrun(cwd: Path) -> tuple[int, str, str]:
    smk = shutil.which("snakemake")
    if smk is None:
        return -1, "", "snakemake not found on PATH"
    proc = subprocess.run(
        [smk, "-n", "--cores", "1"],
        cwd=cwd, capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def classify(stderr: str) -> list[str]:
    hits = []
    for pat, ref, hint in CLASSIFY:
        if pat.search(stderr):
            hits.append(f"  • {pat.pattern} → see {ref}: {hint}")
    return hits


def static_check(cwd: Path) -> tuple[int, list[str]]:
    """Fallback when snakemake is absent. Best-effort structural checks."""
    issues = []
    snakefiles = list(cwd.glob("Snakefile")) + list(cwd.glob("workflow/Snakefile")) + list(cwd.glob("workflow/rules/*.smk"))
    if not snakefiles:
        return 1, ["no Snakefile or workflow/rules/*.smk found"]
    seen = set()
    for sf in snakefiles:
        text = sf.read_text()
        for m in RULE_RE.finditer(text):
            name = m.group(1)
            if name in seen:
                issues.append(f"duplicate rule name: {name}")
            seen.add(name)
        # Heuristic: each rule block should have output + (shell|run). This is
        # approximate (Snakemake DSL is not pure Python) — real validation is
        # the dry-run. Only flag the obviously broken.
        for block in re.split(r"(?=\n\s*rule\s+\w+\s*:)", text):
            if "rule " not in block:
                continue
            if not OUTPUT_RE.search(block):
                continue  # target rules (rule all) may have no output
            if not SHELL_OR_RUN_RE.search(block) and "script:" not in block:
                issues.append(f"rule block without shell/run/script:\n{block.strip()[:120]}")
    return (0 if not issues else 1), issues


def main(argv: list[str]) -> int:
    cwd = Path(argv[1] if len(argv) > 1 else ".")
    if not cwd.exists():
        print(f"validate-workflow: no such dir: {cwd}", file=sys.stderr)
        return 2

    code, stdout, stderr = run_dryrun(cwd)
    if code == -1:
        print("WARNING: snakemake not on PATH — falling back to static-structure check.")
        print("Real validation requires installing snakemake. Output is UNVALIDATED.\n")
        sc_code, issues = static_check(cwd)
        for i in issues:
            print(f"  {i}")
        print(f"\nstatic check: {'PASS (unvalidated)' if sc_code == 0 else 'FAIL'}")
        return sc_code

    print("=== snakemake -n --cores 1 ===")
    if stdout:
        print(stdout)
    if stderr:
        print("=== STDERR (verbatim) ===")
        print(stderr)
    hits = classify(stderr)
    if hits:
        print("\n=== classified (pointers) ===")
        for h in hits:
            print(h)
    print(f"\nexit: {code}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
````

- [ ] **Step 2: Make it executable and verify it parses**

Run: `chmod +x bioinformatics/pipeline-maker/scripts/validate-workflow.py && python3 -m py_compile bioinformatics/pipeline-maker/scripts/validate-workflow.py && echo OK`
Expected: `OK` (no syntax errors).

- [ ] **Step 3: Smoke-check the `--help`-style behavior (snakemake-agnostic)**

Run: `cd /tmp && mkdir -p pvmk-smoke && cd pvmk-smoke && printf 'rule all:\n    input: []\n' > Snakefile && python3 /home/altairwei/src/my-scientific-skills/bioinformatics/pipeline-maker/scripts/validate-workflow.py . 2>&1 | head -15; cd / && rm -rf /tmp/pvmk-smoke`
Expected: either a dry-run attempt (if snakemake is installed) or the static-fallback banner with "snakemake not on PATH" + "UNVALIDATED". Either way, no Python traceback.

- [ ] **Step 4: Commit**

```bash
git add bioinformatics/pipeline-maker/scripts/validate-workflow.py
git commit -m "Add pipeline-maker validate-workflow.py"
```

---

### Task 4: Create `references/snakemake-rules-and-best-practices.md`

**Files:**
- Create: `bioinformatics/pipeline-maker/references/snakemake-rules-and-best-practices.md`

- [ ] **Step 1: Write the file with these sections and concrete content**

Sections (each with the facts/commands below — write the connective prose around them; cite `external/snakemake/docs/snakefiles/rules.rst` by section, do not copy verbatim):

1. **Rule anatomy** — `rule NAME: input/output/log/params/resources/threads/shell|run|script`. Note `:q` quoting (`{input:q}`), bash strict mode by default.
2. **Wildcards** — `{sample}` in output auto-resolves from requested files; wildcard names must match in input and output; constrain with `wildcard_constraints: sample="\d+"` (rule-level or global); multi-wildcard ambiguity (`{a}.{b}.txt` → constrain).
3. **`expand()` / `multiext()` / `collect()` / `lookup()`** — aggregation; `expand("{s}.txt", s=SAMPLES)` resolves at parse time (not a wildcard); `multiext("plot", ".pdf",".png")` for multi-extension outputs (the only way to use between-workflow caching for multi-output rules).
4. **Output flags and their non-obvious semantics** (grounded in `rules.rst` "Protected and Temporary Files" + "Ignoring timestamps"):
   - `protected("f")` — write-protected after the rule completes; this is why stale-code reruns hit `ProtectedOutputException`.
   - `temp("f")` — deleted after all consumers finish; `temp("f", group_jobs=True)` (v9) auto-groups creator+consumer on one node. `temp()` is NOT a rerun trigger (the CODE trigger compares only `rule.shellcmd`/`rule.run_func_src`, never output flags — verified in `persistence/__init__.py` `_code`). Adding `temp()` does not delete prior-run intermediates (use `--delete-temp-output`). Mark shared outputs (e.g., an intervals BED used by all samples) as plain outputs, never `temp()`.
   - `directory("d")` — explicit directory output; creates `.snakemake_timestamp` whose mtime is used for up-to-date checks (avoids dir-mtime churn). The dir is deleted before the job runs — other jobs must not write into it.
   - `ancient("f")` — input mtime ignored, assumed older than outputs; prevents rerun on mtime change.
   - `touch("f")` — Snakemake touches (creates/updates) the file after the command succeeds; for sentinel/done files.
5. **`output:` must be concrete paths** — strings or `expand()`/`multiext()`. Functions/lambdas are allowed only in `input:`/`params:`/`resources:`; a bare function ref or lambda in `output:` errors (`Only input files can be specified as functions`). Pass called results in `output:` (e.g., `get_log_path(...)`, not `get_log_path`).
6. **Reserved output field names** — `count` is reserved (and there may be others); if a dry-run rejects an output field name, rename it.
7. **Verify a flag/helper exists before use** — `optional()` is NOT a built-in (the WGS agent hit this NameError). Before assuming a flag exists, `rg` the vendored source or `python -c "import snakemake; ..."`.
8. **Shell brace-escaping** — single braces are Snakemake format placeholders; to emit a literal `{` in a shell string (e.g., a bash variable `${gendb_path}`), write `{{` → `${{gendb_path}}`. To emit `{input}` literally in a comment, mask with `{{input}}`.
9. **`shell:` vs `run:` vs `script:`** — `shell:` for one-liners (bash strict mode); `run:` for a few lines of Python (access `input`/`output`/`wildcards`/`params`/`log`/`threads`/`resources`/`config` directly; keep it short, else use `script:`); `script:` for `scripts/*.{py,R,Rmd,jl,rs,sh,xsh,hy}` — path is relative to the Snakefile; inside the script use the `snakemake` object (`snakemake.input[0]`, `snakemake@input[[1]]` in R, 1-indexed in R/Julia/Rust).
10. **Standard resources** — `mem`/`disk`/`runtime`/`tmpdir` (strings with units) or `mem_mb`/`disk_mb` (ints); `runtime` as minutes-int or string (`"2h"`); `tmpdir` sets `$TMPDIR`; `gpu`/`gpu_manufacturer`/`gpu_model`. Resources are totals per job, not per thread. Default-resources formula: `mem_mb=min(max(2*input.size_mb, 1000), 8000)`, `disk_mb=max(2*input.size_mb, 1000) if input else 50000`, `tmpdir=system_tmpdir`. Dynamic resources: callables `callable(wildcards[, input, threads, attempt])` — use `attempt` to scale mem on retry (`--retries`).
11. **Checksum-vs-mtime** — for input files ≤1MB (default, `--max-checksum-file-size`), Snakemake records and compares checksums and only reruns if the checksum changed; for larger inputs, mtime comparison. `ancient()` overrides; `directory()` uses `.snakemake_timestamp`.

- [ ] **Step 2: Verify size and accuracy spot-check**

Run: `./count-skill-tokens.py bioinformatics/pipeline-maker`
Expected: cumulative total still manageable (SKILL.md was the bulk; each reference should be a few hundred tokens). Spot-check: `grep -n "temp().*NOT a rerun trigger\|optional().*not.*built-in\|output:.*concrete" bioinformatics/pipeline-maker/references/snakemake-rules-and-best-practices.md` shows the three load-bearing facts are present.

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/pipeline-maker/references/snakemake-rules-and-best-practices.md
git commit -m "Add snakemake-rules-and-best-practices reference"
```

---

### Task 5: Create `references/modularization-and-config.md`

**Files:**
- Create: `bioinformatics/pipeline-maker/references/modularization-and-config.md`

- [ ] **Step 1: Write the file with these sections and concrete content**

1. **Stage-per-file layout** — `workflow/rules/<stage>.smk` (one file per pipeline stage: e.g., `alignment.smk`, `variant_calling.smk`, `quality_control.smk`). The main `workflow/Snakefile` (or root `Snakefile`) loads config and `include:`s the stage files. This is the layout observed in the WGS pipeline.
2. **`common.smk` for shared helpers** — rule-formatting helpers (e.g., a `get_vqsr_resource_args`-style builder that pairs `--resource:label,key=… <vcf>`, a `get_log_path(wildcards, rule_name)` resolver). Pure analysis logic goes in `scripts/*.py`, not `common.smk`. Helpers are called (not bare-referenced) in directives.
3. **`config.yaml` + `configfile:`** — `configfile: "config.yaml"` in the Snakefile; access via `config["key"]` or `config["section"]["key"]`. Put samples, paths, and tunable params here. **New samples are added in `config.yaml`, never by editing the Snakefile.** Multi-sample: a `config/samples.tsv` table (fastq→sample-id mapping) read by an input function or `lookup()`.
4. **Modules (Snakemake 8+)** — `module name: snakefile: "path"` + `use rule name.* from name as alias_*`. Prefer `include:` for simple in-repo stage files; use `module`/`use rule` for importing external/reusable workflows. `snakedeploy deploy-workflow` for templated deployment of published workflows.
5. **`pathvars` (Snakemake 9+)** — `<results>`/`<logs>` etc. placeholders in input/output/log paths, configurable globally or per-rule; defaults `results`/`stats`/`reports`/`temp`/`resources`/`logs`/`benchmarks`. Useful for reusable modules.
6. **Target rules** — `rule all:` (or `default_target: True`) as the first rule; `expand()` the final outputs. Optional stage targets (e.g., `alignment_all`, `variant_calling_all`) invoked explicitly like the default target.
7. **`localrules:`** — declare rules that must run on the orchestrator node (e.g., a `create_intervals` BED generator that writes a shared file) via `localrules: create_intervals` at the top of the stage file.

- [ ] **Step 2: Verify size**

Run: `./count-skill-tokens.py bioinformatics/pipeline-maker`
Expected: cumulative total still < the SKILL.md budget per-file.

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/pipeline-maker/references/modularization-and-config.md
git commit -m "Add modularization-and-config reference"
```

---

### Task 6: Create `references/rerun-and-metadata.md`

**Files:**
- Create: `bioinformatics/pipeline-maker/references/rerun-and-metadata.md`

- [ ] **Step 1: Write the file with these sections and concrete content**

This is the proactive state-management reference. Ground every fact in `persistence/__init__.py` + `settings/enums.py` + `cli.py`; cite by function/line, do not copy.

1. **The five `RerunTrigger`s** (enum `settings/enums.py`: `MTIME`, `PARAMS`, `INPUT`, `SOFTWARE_ENV`, `CODE`; default = all five):
   - **CODE** — compares the rule's shell text (`rule.shellcmd`) or run-block source (`rule.run_func_src`); for `script:`/`notebook:` rules, the script file's mtime. Source: `persistence/__init__.py` `_code()` (lru-cached, returns `rule.shellcmd` or `rule.run_func_src` or None). **This is the stale-code trap**: editing a rule's shell text retroactively invalidates all prior outputs of that rule. Adding `temp()`/`protected()` does NOT change `_code` → no rerun.
   - **INPUT** — compares the sorted set of input file paths (`_input()`; pipe→`<pipe>`, service→`<service>`, storage paths). Not input mtime — the input *path set*.
   - **PARAMS** — compares non-derived `params:` values (serialized via `_serialize_param`; pandas objects hashed). Derived params (from input/output) are captured by INPUT. Format-version gated (v6+). Changing a `params:` value reruns.
   - **SOFTWARE_ENV** — conda env content hash / container image URL / env-modules hash (`_software_stack_hash()`).
   - **MTIME** — an input file's mtime newer than the output's; for inputs ≤1MB, checksum instead (only rerun if checksum changed). `ancient()` ignores mtime; `directory()` uses `.snakemake_timestamp`.
2. **`--rerun-triggers`** — choose a subset; default all five. Production runs often use `--rerun-triggers mtime input` to exclude CODE (accepting stale-code outputs as valid — a deliberate trade-off). `--allowed-rules` is the WRONG mechanism for rerun control.
3. **The per-output metadata record** — stored under `.snakemake/metadata/` with a **base64-encoded path filename** (decode with `python3 -c "import base64; print(base64.b64decode(fn).decode())"`). Each record stores: `code`, `input`, `log`, `params`, `conda_env`, `software_stack_hash`, `container_img_url`, `input_checksums`, `endtime`, `starttime`, `rule`, `record_format_version`. Inspect with a small Python script.
4. **Incomplete markers** — marked on `started(job)` (`_mark_incomplete` for each output), cleared on `finished(job)` (which also writes the record). `incomplete(job)` returns outputs that are BOTH marked AND exist on disk. A force-stopped job leaves markers → `IncompleteFilesException` on next run.
5. **`--rerun-incomplete` (`--ri`)** — re-run all jobs whose output is marked incomplete. `--keep-incomplete` — keep incomplete output files from failed jobs (default deletes them).
6. **`--cleanup-metadata FILE…` (`--cm`)** — `cleanup_metadata()` calls `_unmark_incomplete(key)` then `_delete_record(key)`: removes BOTH the incomplete marker AND the metadata record. Use it on the **entire affected output subtree** (every output with a pre-change record, ~55 files per single-run sample in the WGS case) to escape the stale-code trap. Benign `WorkflowError: metadata was not present` for already-clean files is fine. **Build the cleanup list from files actually present on disk per sample's full output subtree** — and the code-change source may be ANY commit on ANY rule (the WGS agent missed `bwa_mem2_mem`'s `unit{unit}/aligned.sorted.bam` because it only thought about GATK/d05065d; bwa's `-@ 24→-@ 2` from a different commit also fired "Code has changed"). Use `git log -- <rulefile>` to find all commits touching a rule's shell text.
7. **`--list-changes` / `--list-input-changes` / `--list-params-changes`** — diagnose what the trap will invalidate BEFORE running.
8. **`--forcerun` (`-R`) / `--force` (`-f`) / `--forceall` (`-F`)** — force rerun of given rules/files / the target / the target + all dependencies. Use `-R` when you changed a rule and want all its output updated.
9. **`--delete-temp-output` / `--delete-all-output`** — reclaim disk. **Always `--dry-run` first** (lists what would be deleted). Skips `protected()`. Does not recurse subworkflows. Adding `temp()` does not auto-delete prior-run intermediates — that's what `--delete-temp-output` is for.
10. **`--consider-ancient RULE=INPUTITEMS`** — overrule the mtime trigger for known-stable inputs.
11. **`--drop-metadata`** — stop tracking metadata after jobs finish (faster, but disables CODE/PARAMS/SOFTWARE triggers — only mtime remains).
12. **Stale-code trap workflow** — before resuming after a rule edit: (a) `git log` the rule file to find all shell-text-changing commits since the outputs were made; (b) build the cleanup list = every rule output in the affected samples' subtrees (cram/crai + every intermediate, including BWA unit BAMs); (c) `snakemake --cleanup-metadata <all those paths>`; (d) dry-run + `--rerun-incomplete`; (e) verify no `ProtectedOutputException` and `Code has changed` count = 0. Distinguish stale-code (data-valid, e.g., `-Xmx` only bounds the JVM heap, doesn't change results → cleanup-metadata to accept) from incomplete (force-stopped → `--rerun-incomplete` to rebuild).
13. **Force-stop recovery** — dry-run to enumerate incomplete files (named in `IncompleteFilesException`); classify them as "to rebuild" (not "completed"); resume with `--rerun-incomplete`; do not delete their intermediates. Watch for interrupted final outputs (e.g., a cram written but its `.crai` missing) — these are untrusted and must be rebuilt.
14. **Large-DAG dry-run** — `--batch RULE=I/N` (official batching) or a `--configfile /tmp/override.yaml` collapsing scatter (e.g., `bqsr: {scatter_intervals: 1}`) to validate shell rendering cheaply. `--rerun-triggers mtime` to focus. Note: `--config` CLI rejects dotted keys — use a `--configfile` override. Large-cohort dry-runs time out on shared filesystems (DAG build >8 min for 529 samples × ~60 jobs) — use single-sample dry-runs as safety checks first.
15. **CLI `nargs='+'` footguns** — `--rerun-triggers` and `--quiet` are `nargs='+'` in v9 and greedily eat following positional targets → put targets BEFORE these flags or use `--` to separate. (The WGS agent hit this 3+ times.)
16. **Running orchestrator caches config** — a running snakemake orchestrator caches `config.yaml` at start; resource edits need a restart to take effect.
17. **`temp()` outputs are deleted once consumed** → a downstream re-run needs them regenerated — don't `temp()` outputs you might re-run against unless regeneration is cheap.
18. **Stale locks** — orphan/stale orchestrators hold the directory lock (`LockException` for new runs). `kill -9 <pid>` the orphan, then `snakemake --unlock`.
19. **Post-hoc in-place output edits** — when converting an output format in place (e.g., CRAM 3.1→3.0 for tool compatibility), preserve the mtime (`samtools ... && touch -r <ref> <out>`) so `--rerun-triggers mtime input` doesn't trigger downstream reruns.
20. **`workflow.source_path` from `params:` causes spurious reruns** — it returns a cached path that may change between runs; use it only from `input:`, never `params:`.

- [ ] **Step 2: Verify size and that the load-bearing facts are present**

Run: `./count-skill-tokens.py bioinformatics/pipeline-maker` and `grep -cE "RerunTrigger|cleanup-metadata|rerun-incomplete|delete-temp-output|nargs|base64|stale-code|temp\(\).*deleted once" bioinformatics/pipeline-maker/references/rerun-and-metadata.md`
Expected: size still bounded; grep count ≥ 8.

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/pipeline-maker/references/rerun-and-metadata.md
git commit -m "Add rerun-and-metadata reference"
```

---

### Task 7: Create `references/debugging.md`

**Files:**
- Create: `bioinformatics/pipeline-maker/references/debugging.md`

- [ ] **Step 1: Write the file with these sections and concrete content**

Reactive dry-run error diagnosis using the real exception vocabulary. For each: cause, the snakemake message shape, the fix. `ProtectedOutputException`, `IncompleteFilesException`, and "Code has changed" point to `rerun-and-metadata.md`.

1. **`MissingInputException`** — no rule produces a requested input, or a wildcard resolves to nothing. Fix: add a producer rule, fix the input path/wildcard, or mark the file `ancient()`/provide it externally.
2. **`MissingOutputException`** — a rule finished but a declared output is missing. Fix: check the rule's command actually writes the declared path (common: typo in output path, command writes elsewhere, job killed mid-write).
3. **`AmbiguousRuleException`** — multiple rules can produce the same output. Fix: constrain wildcards (`wildcard_constraints`), add `ruleorder: a > b`, or make rule outputs disjoint.
4. **`WildcardError`** — unconstrained or ambiguous wildcard (e.g., `{a}.{b}.txt` matching `1.2.3.txt`). Fix: `wildcard_constraints` with regexes.
5. **`WorkflowError`** — broad; read the message. Common sub-cases: `metadata was not present` (benign after cleanup-metadata), `Directory cannot be locked` (see stale locks in `rerun-and-metadata.md`), `MissingRuleException` (usually a path-construction bug in your own command — check doubled path components).
6. **`ProtectedOutputException` / `IncompleteFilesException` / "Code has changed"** → load `rerun-and-metadata.md`. Note: `ProtectedOutputException` is thrown BEFORE DAG construction (with `--rerun-incomplete` on a protected output needing rerun), so no `reason` detail is shown — to capture the reason, temporarily `chmod u+w` the protected output, dry-run to read the reason, then re-protect.
7. **CLI invocation footguns** — `--rerun-triggers` and `--quiet` are `nargs='+'` in v9 (eat following positional targets — put targets first or use `--`). `--reason` is gone in v9 (rerun reasons are always shown).
8. **A dry-run validates DAG/syntax but NOT runtime tool-argument semantics** — multi-arg tool flags (e.g., GATK `--resource:label,key=… <vcf>`, which must pair the label with the VCF as the NEXT argument) need manual re-reading of tool docs; the dry-run won't catch them. Re-read your rules for multi-arg tool flags before declaring done.
9. **Tool reproducibly crashes on valid input** — do not loop retries. Reproduce on a small slice (proves it's not scale-related), then substitute an equivalent (`bcftools query | awk` for a crashing `vcftools`) and validate equivalence against the original (e.g., bin-by-bin identical counts) before declaring success.
10. **Debugging aids** — log files in `.snakemake/log/`; `--skip-script-cleanup` (keep wrapper scripts for `script:` rules); target a single output to shrink the DAG (`snakemake path/to/output.file`); `--debug` for PDB in `run:`/scripts; `--nolock` to avoid holding the lock during long dry-runs.
11. **`du` on subtrees with hardlinks overcounts** — when measuring reclaimable space, don't trust `du` on subtrees with hardlinks/shared paths (it double-counts, reporting nonsense like 54 PB for 348 samples). Sum reclaimable space from the `--delete-temp-output --dry-run` preview list directly, with dedup.

- [ ] **Step 2: Verify size and accuracy**

Run: `./count-skill-tokens.py bioinformatics/pipeline-maker` and `grep -cE "MissingInput|AmbiguousRule|nargs|dry-run validates|tool-argument|du.*overcount" bioinformatics/pipeline-maker/references/debugging.md`
Expected: size bounded; grep count ≥ 5.

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/pipeline-maker/references/debugging.md
git commit -m "Add debugging reference"
```

---

### Task 8: Create `references/deployment.md`

**Files:**
- Create: `bioinformatics/pipeline-maker/references/deployment.md`

- [ ] **Step 1: Write the file with these sections and concrete content**

1. **Conda envs** — `workflow/envs/<tool>.yaml` (channels: conda-forge, bioconda; dependencies pinned); per-rule `conda: "envs/<tool>.yaml"` directive. Snakemake auto-activates. `--sdm conda` to enable.
2. **Apptainer/containers** — `container: "docker://img"` or `container: "oras://..."` per rule; `--sdm apptainer` to enable. Container must contain the shell (`resources: shell_exec="sh"` if no bash).
3. **Executor plugins (Snakemake 8+)** — `--executor slurm|local|kubernetes|...`; SLURM via the `snakemake-executor-plugin-slurm`. Configuration boils down to executor + optional storage plugin (e.g., S3).
4. **Profiles** — `profiles/<env>/profile.yaml` (global = compute environment; workflow-specific = `workflow/profiles/<env>/` or `--workflow-profile`). Keys: `executor`, `jobs`, `cores`, `default-resources`, `set-threads`, `set-resources`, `set-scatter`, `rerun-triggers`, `keep-going`. Precedence: CLI > workflow-profile > global-profile. Multiple `--profile` merge (later wins).
5. **Profile is the authority layer** — a profile's `set-resources: <rule>: mem_mb: N` OVERRIDES both the rule's `resources:` directive AND `config.yaml`. When changing a rule's memory, edit BOTH `config.yaml` AND the profile's `set-resources`, then verify the actual `mem_mb`/`-Xmx` a job would get via a dry-run (the WGS agent's config-only edit silently didn't apply — the profile pinned 8192). A running orchestrator caches config at start, so resource edits need a restart to take effect.
6. **Resource sizing & scatter** — `resources: mem_mb=`/`runtime=`; dynamic resources via `attempt`/`input.size_mb` callables (e.g., `mem_mb=lambda wc, attempt: attempt * 200` for OOM-retry scaling with `--retries`). Some tools scale memory with `interval × samples + a fixed per-sample overhead` (NOT just input size) — GenomicsDBImport/GenotypeGVCFs OOM'd at 24 GB for whole-chromosome intervals over 529 samples. Fix: scatter over a FINER sub-interval set (`set-scatter` or a `create_genotype_intervals` localrule producing 16 Mb pieces) AND bump `mem_mb` rather than retry. The OOM MaxRSS (~25 GB) was only ~1 GB over the 24 GB cap → 40 GB gave ample headroom.
7. **`--tmp-dir` must be absolute** — GATK `--tmp-dir .` resolves to cwd (project root) and scatters `libgkl*`/`libtiled*`/`loader_*`/`tmp_read_*` temp files in the project root. Use an absolute scratch path (`--tmp-dir /scratch/$SLURM_JOB_ID` or `resources: tmpdir=choose_tmp([...])`).
8. **Track `profiles/` in git** — per-rule memory budget is essential for full runs; even if `profiles/` is gitignored by default, track it (the WGS user explicitly un-ignored it: "毕竟内存用量对于 pipeline 完整运行来说还是挺重要的"). Ensure no secrets (keys/passwords) are in the profile before committing.
9. **SLURM `squeue`/`sacct` polling** — belongs to `bioinfo-project-organization`'s `runall`, not here. (Note: `squeue -j <gone>` exits 0 with empty output — poll output, not exit code; `sacct` state must be whitespace-trimmed.)

- [ ] **Step 2: Verify size**

Run: `./count-skill-tokens.py bioinformatics/pipeline-maker`
Expected: size bounded.

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/pipeline-maker/references/deployment.md
git commit -m "Add deployment reference"
```

---

### Task 9: Create `references/bash-to-workflow.md`

**Files:**
- Create: `bioinformatics/pipeline-maker/references/bash-to-workflow.md`

- [ ] **Step 1: Write the file with these sections and concrete content**

Ports snkmaker's bash-mode methodology (study `external/snkmaker/README.md`; do not copy).

1. **Collect commands** — accept pasted commands, a history file, or a shell-history export. Ask the user for any missing context (which files exist, what's a sample id).
2. **Classify important vs one-timer** — important commands contribute to the workflow (transforms files); one-timers (ls, cd, quick look) are skipped. Ask the user on ambiguity; defaults can be flipped.
3. **Extract I/O and infer rule names** — for each important command, identify input files (read) and output files (written, including `>`/`-o`/`--out`/`2>` redirections), and infer a rule name (from the tool, the output stem, or ask the user). Editable.
4. **Detect composite opportunities** — multiple commands that together produce one output (e.g., `samtools sort | samtools index` → one rule) → merge into a composite rule.
5. **Infer wildcard generalization** — if the same command is run over many files differing only in a sample/dataset token, generalize to a wildcard rule (`{sample}.fastq → {sample}.bam`). **Present the inference and let the user confirm before generalizing across samples** — over-generalization is a judgment call.
6. **Build the dependency DAG** — match each command's input files to other commands' outputs; order the rules. Detect cycles and missing producers.
7. **Decide rule vs script** — a command that reads a file output by another rule and can be expressed as a shell one-liner → rule; a command with complex logic or many steps → a `script:` (writes `scripts/*.py`/`.sh`) called by a thin rule. (Cascading constraint with notebooks — see `notebook-to-workflow.md`.)
8. **Generate rules** — from `assets/rule.tmpl` / `assets/workflow-rules.smk.tmpl`, fill `<NAME>`/`<INPUT>`/`<OUTPUT>`/`<COMMAND>`; write `Snakefile` + `config.yaml` (+ `common.smk` if shared helpers). Keep the `log:` directive (survives failures).
9. **GNU Make alternative** — snkmaker can also emit Make rules; this skill is Snakemake-only. If the user asks for Make, point them to snkmaker directly.

- [ ] **Step 2: Verify size**

Run: `./count-skill-tokens.py bioinformatics/pipeline-maker`
Expected: size bounded.

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/pipeline-maker/references/bash-to-workflow.md
git commit -m "Add bash-to-workflow reference"
```

---

### Task 10: Create `references/notebook-to-workflow.md`

**Files:**
- Create: `bioinformatics/pipeline-maker/references/notebook-to-workflow.md`

- [ ] **Step 1: Write the file with these sections and concrete content**

Ports snkmaker's notebook-mode methodology (study `external/snkmaker/README.md` "Notebook support"; do not copy).

1. **Parse cells** — read the notebook (`*.ipynb`, JSON); for each cell, identify three sets of variables:
   - **Read** — variables the cell (might) read from other cells.
   - **Write** — variables the cell (might) write to be used by other cells.
   - **Wildcards** — variables the cell (might) read that will be provided as Snakemake wildcards.
2. **Build the dependency DAG** — match each **Read** of a cell to the closest prior **Write** of that variable. This gives the cell-to-cell dependency graph.
3. **Split / merge / remove cells** — the user can split a cell into two rules, merge cells, or remove cells to fit the workflow. Refine the variable sets manually (add/remove Read/Write/Wildcards).
4. **Rule-vs-Script cascading constraint** — decide each cell as **Rule** or **Script**:
   - A **Rule** can read output files from other rules and import scripts → can depend on both Rules and Scripts. Any cell can become a Rule.
   - A **Script** can import other scripts but CANNOT directly read a file output by another rule → can depend only on Scripts.
   - Therefore: setting a cell as a Rule may cascade — forcing dependent Scripts to become Rules too (so they can read the rule's output). All cells must be Rule or Script before generation; undecided cells are flagged.
5. **Generate prefix + suffix code** — for each cell set as a Rule, generate:
   - **Prefix code** — import statements, command-line-argument reading, and reading of input files (from `snakemake.input`).
   - **Suffix code** — writing of output files (to `snakemake.output`).
   - The body is the cell's original code. For Script cells, only prefix (no suffix).
6. **Auto-propagate edits** — if the user edits the generated code (e.g., changes an output format), the change propagates to dependent cells' rules/prefixes (update the rule's output filename; update readers' input + prefix).
7. **Export** — write `Snakefile` + `scripts/*.py` (one per cell that became a Script or Rule body) to a directory the user chooses.
8. **Validate** — run `validate-workflow.py`; fix loop.

- [ ] **Step 2: Verify size**

Run: `./count-skill-tokens.py bioinformatics/pipeline-maker`
Expected: size bounded.

- [ ] **Step 3: Commit**

```bash
git add bioinformatics/pipeline-maker/references/notebook-to-workflow.md
git commit -m "Add notebook-to-workflow reference"
```

---

### Task 11: Register the skill in `marketplace.json` and `README.md`

**Files:**
- Modify: `.claude-plugin/marketplace.json` (the `bioinformatics` plugin's `skills` array)
- Modify: `README.md` (the `bioinformatics` category table)

- [ ] **Step 1: Add the skill to the `bioinformatics` plugin's `skills` array**

In `.claude-plugin/marketplace.json`, append `"./bioinformatics/pipeline-maker"` to the `skills` array of the `bioinformatics` plugin (after `"./bioinformatics/bioinfo-project-organization"`), keeping valid JSON (trailing comma after the previous entry, no trailing comma after the new last entry).

Expected resulting array:
```json
"skills": [
  "./bioinformatics/population-genomics",
  "./bioinformatics/bioinfo-project-organization",
  "./bioinformatics/pipeline-maker"
]
```

- [ ] **Step 2: Verify JSON is valid**

Run: `python3 -c "import json; json.load(open('.claude-plugin/marketplace.json')); print('valid')"`
Expected: `valid`.

- [ ] **Step 3: Add a row to the README.md `bioinformatics` category table**

After the `bioinfo-project-organization` row, add:

```markdown
| [pipeline-maker](bioinformatics/pipeline-maker/) | Build or recover a reproducible, modular Snakemake workflow from ad-hoc bash, a Jupyter notebook, or a described goal; mandatory `snakemake -n` dry-run loop, stale-code/force-stop/temp-cleanup recovery |
```

- [ ] **Step 4: Commit**

```bash
git add .claude-plugin/marketplace.json README.md
git commit -m "Register pipeline-maker in marketplace and README"
```

---

## Self-review (run before handing off)

**Spec coverage:** SKILL.md (Task 1) ✓; 7 references (Tasks 4–10) ✓; 5 assets (Task 2) ✓; validate-workflow.py (Task 3) ✓; registration (Task 11) ✓; working-discipline recovery + execution-consent + feature-grounding (Task 1) ✓; real exception vocabulary in the script (Task 3) + debugging.md (Task 7) ✓; rerun-trigger source-grounding (Task 6) ✓; profile-authority + resource-sizing + `--tmp-dir` + track-profile (Task 8) ✓; output-must-be-concrete + reserved-names + optional-not-builtin (Task 4) ✓; nargs footgun (Tasks 6, 7) ✓; bash + notebook methodology (Tasks 9, 10) ✓.

**Placeholder scan:** every step has concrete content (actual file content for SKILL.md/assets/script; concrete section + facts/commands/source-citations for each reference). No "TBD"/"implement later".

**Type/name consistency:** `validate-workflow.py` exception list (Task 3) matches `debugging.md` vocabulary (Task 7): `ProtectedOutputException`, `IncompleteFilesException`, "Code has changed" → `rerun-and-metadata.md`; `MissingInputException`, `MissingOutputException`, `AmbiguousRuleException`, `WildcardError`, `WorkflowError` → `debugging.md`. SKILL.md references-pointer names (Task 1) match the filenames created in Tasks 4–10. Asset filenames (Task 2) match the references in SKILL.md and the data-contract.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-04-pipeline-maker.md`. Two execution options:

1. **Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
