# Design: `pipeline-maker` Skill

Date: 2026-08-04
Status: Approved by user (core purpose, domain/placement, output granularity,
validation policy, structure approach, recovery discipline, real exception
vocabulary, `common.smk.tmpl` asset; testing deferred to real-world use). v2
adds a 7th reference `rerun-and-metadata.md` grounded in snakemake docs/source
and a fourth source — empirical WGS session data.

## Goal

A skill that teaches Claude how to build reproducible, modular Snakemake
workflows from two entry points, and how to recover a misbehaving run:

1. **Ad-hoc → workflow** — transform unstructured bash command history or a
   Jupyter notebook into a Snakemake workflow (the methodology of
   [`snkmaker`](https://arxiv.org/abs/2505.02841), ported into a Claude skill).
2. **From-scratch → workflow** — author a Snakemake pipeline from a described
   analysis goal and a data manifest.
3. **Recovery** — diagnose and safely recover rerun storms ("Code has changed"),
   `ProtectedOutputException`, `IncompleteFilesException` after a force-stop,
   and disk-bloat from un-reclaimed intermediates.

All three produce the same modular output and are gated by a mandatory dry-run
validation-and-correction loop. The skill is domain-agnostic (examples are
general-first, bioinformatics-secondary) and lives in `bioinformatics/`
alongside the existing analysis skills, deferring project-level layout to
`bioinfo-project-organization`.

## Source & positioning

Four sources, studied (not copied) per the repo's `external/` policy in
`CLAUDE.md`:

- **`external/snkmaker`** — the methodological source. A VS Code extension
  (TypeScript, MVVM) that uses an LLM to turn bash commands or notebooks into
  Snakemake workflows. The skill ports its *methodology*, not its GUI: command
  classification (important vs one-timer), I/O extraction, rule-name inference,
  composite-rule merging, wildcard generalization, the validate-with-`snakemake`
  -then-correct loop (bash mode), and the Read/Write/Wildcards dependency
  resolution + Rule-vs-Script decision + prefix/suffix codegen (notebook mode).
- **`external/snakemake/docs`** — the correctness reference. `getting_started/`,
  `tutorial/`, `snakefiles/` (rules, writing_snakefiles, best_practices,
  modularization, configuration, debugging, deployment, storage, testing,
  reporting), `executing/` (cli, caching, grouping, executors, provenance).
- **`external/snakemake/src`** — the Python source; consulted to verify rule
  semantics, rerun-trigger comparisons (`persistence/__init__.py`: `_code`,
  `_code_changed`, `_input_changed`, `params_changed`, `_software_stack_changed`,
  `incomplete`, `cleanup_metadata`), and the `RerunTrigger` enum
  (`settings/enums.py`: `MTIME`, `PARAMS`, `INPUT`, `SOFTWARE_ENV`, `CODE`).
  Never copied.
- **`external/session_files/...-WGS-pipeline`** — empirical grounding: a real
  Claude Code session that built a 529-sample WGS Snakemake pipeline. The
  distilled 10 memory files and the **actual conversation transcripts**
  (alignment/force-stop and variant-calling sessions — read in extract: every
  user prompt, agent reasoning line, every `snakemake` command, every `.smk`
  write — not just grep counts) quantify what goes wrong and how the agent
  recovers: `WorkflowError` 224, `ProtectedOutputException` 157,
  `MissingInputException` 112, "Code has changed" 73, `IncompleteFilesException`
  52; recovery operations `--rerun-triggers` 435, `--dry-run` 419,
  `--delete-temp-output` 228, `--rerun-incomplete` 189, `--cleanup-metadata` 58;
  rule files written as `workflow/rules/<stage>.smk` + `common.smk` +
  `profiles/slurm/config.yaml`. These drive the recovery discipline, the real
  exception vocabulary, and the `common.smk.tmpl` asset below.

All reference material is **rewritten originally** in the skill's
`references/*.md`; nothing is copied verbatim from `external/` (license respect,
per `CLAUDE.md`).

Scope is deliberately the **Snakemake-workflow construction + recovery core**.
Out of scope for v1 (see below): Nextflow/WDL/other engines, Make-rule output,
full project scaffolding, and snkmaker's GUI-only features (terminal-history
recording, the Copilot-chat assistant).

## Skill structure

```
bioinformatics/pipeline-maker/
├── SKILL.md                      # ~300–400 lines, < 5000 tokens
├── references/                   # load on demand, each self-contained
│   ├── bash-to-workflow.md           # snkmaker bash-mode methodology
│   ├── notebook-to-workflow.md       # snkmaker notebook-mode methodology
│   ├── snakemake-rules-and-best-practices.md  # rule syntax, flags, shell escaping, best practices
│   ├── modularization-and-config.md  # workflow/rules/ + config.yaml + common.smk + modules
│   ├── deployment.md                 # conda/containers/SLURM profile + resource sizing & scatter
│   ├── rerun-and-metadata.md         # rerun triggers, metadata, incomplete, temp/protected, recovery
│   └── debugging.md                  # dry-run error diagnosis (real exception vocabulary)
├── assets/                       # drop-in skeletons, filled per task
│   ├── Snakefile.tmpl                # main entry: configfile + include rules
│   ├── config.yaml.tmpl              # samples + paths + params placeholders
│   ├── rule.tmpl                     # single-rule skeleton (input/output/log/params/shell)
│   ├── workflow-rules.smk.tmpl       # modular rule file with wildcard example
│   └── common.smk.tmpl               # shared helper functions (e.g. resource-arg builders)
└── scripts/
    └── validate-workflow.py       # runs `snakemake -n`, classifies errors, static fallback
```

### SKILL.md outline

- **Frontmatter**: `name: pipeline-maker`; `description` (trigger, below)
  < 100 tokens, slightly pushy per repo convention; `metadata: {author:
  Altair Wei, version: "1.0"}`; `license: MIT`.
- **Title + one-line intro** — build or recover a reproducible, modular
  Snakemake workflow.
- **Working discipline** — habits for every task:
  - *Generation*: confirm entry mode & input shape before generating; plan first
    (rule list / DAG) and confirm with the user before writing code; generate
    rule-by-rule or in small auditable batches, never dump an unverified
    Snakefile; ground directives in the relevant reference or `snakemake --help`
    for the installed version, do not recall from memory; treat wildcard
    generalization, rule-vs-script splits, and conda granularity as judgment
    calls — present options and let the user decide; defer project-level layout
    to `bioinfo-project-organization`.
  - *Validation*: run the dry-run loop after every generation/edit, read the
    real stderr, fix, retry; after 2–3 failed fixes on the same error, stop and
    report the diagnosis. Never declare done until `snakemake -n` passes (or
    the output is explicitly flagged "unvalidated" via the static fallback).
  - *Recovery* (the high-frequency mistakes): before any destructive or
    metadata-altering operation (`--delete-temp-output`, `--delete-all-output`,
    `--cleanup-metadata`, `--force`), run a `--dry-run` first and read what it
    would touch. Before editing a rule's shell text / a `params:` value / a
    conda env on a workflow with completed outputs, assess which jobs the
    CODE/PARAMS/SOFTWARE trigger will invalidate (`--list-changes` /
    `--list-input-changes` / `--list-params-changes`); to keep valid outputs,
    `--cleanup-metadata` the **entire affected output subtree**, not just the
    obvious file. After a force-stop, do NOT treat present files as complete —
    dry-run to enumerate `IncompleteFilesException` files, then resume with
    `--rerun-incomplete` without deleting their intermediates. `temp()` reclaims
    disk but is NOT a rerun trigger and does NOT auto-delete prior-run
    intermediates — use `--delete-temp-output`; mark shared outputs (e.g., an
    intervals BED used by all samples) as plain outputs, never `temp()`. When
    a tool reproducibly crashes on valid input (e.g., a glibc heap corruption),
    do not loop retries — substitute an equivalent and validate equivalence
    against the original before declaring success. Before trusting pipeline
    defaults that depend on cohort composition (e.g., chrX/chrY diploid ploidy,
    MAF cutoffs), verify the assumption (coverage-ratio sex check, cohort
    composition) and state it. Companion analysis scripts go in tracked
    `scripts/` or `experiments/`, never in gitignored `results/`.
  - *Execution consent*: never launch a real pipeline run or a SLURM orchestrator
    without explicit user permission — default to `--dry-run`. The WGS user was
    repeatedly burned by unauthorized auto-runs (an orphan `multiqc` orchestrator
    held the directory lock for 9 days; a full `variant_calling_all` run launched
    unbidden). A dry-run is always safe; a real run is not.
  - *Feature grounding*: confirm a Snakemake flag/helper exists in the installed
    version before using it (`optional()` is not a built-in; `update()`/`branch()`/
    `--executor touch` need v9+) — `rg` the vendored source or `python -c "import
    snakemake"`, never assume from memory.
- **Workflow map — Mode A (bash/notebook → workflow)** — collect commands;
  classify important vs one-timer; extract I/O, infer rule names, decide
  rule-vs-script; detect composite opportunities and wildcard generalization;
  build the dependency DAG; generate rules from templates; validate. The
  notebook sub-path adds Read/Write/Wildcards dependency resolution, the
  Rule-vs-Script cascading constraint, and prefix/suffix codegen, exporting
  `scripts/*.py` alongside the rules.
- **Workflow map — Mode B (from-scratch)** — clarify the goal and data
  manifest (inputs, samples table, reference, tools); decompose into steps
  naming tool/inputs/outputs/params; decide rule granularity and wildcard
  strategy and sketch the DAG; generate the modular scaffold from assets;
  optional conda envs; validate.
- **Workflow map — Recovery** — when the user reports a rerun storm,
  `ProtectedOutputException`, incomplete files after a crash, or disk bloat:
  load `rerun-and-metadata.md`; diagnose with `--list-changes` / a focused
  `--dry-run`; classify (incomplete ≠ complete; stale-code ≠ data-invalid);
  recover with the right combination of `--cleanup-metadata` (whole subtree),
  `--rerun-incomplete`, `--delete-temp-output` (always dry-run first), or
  `--forcerun`; verify no `ProtectedOutputException` remains.
- **Data contract** — input shapes (bash history, notebook, prose steps, goal
  description, samples TSV); output layout (`Snakefile` + `config.yaml` +
  `workflow/rules/*.smk` + `common.smk` for shared helpers + `scripts/` +
  optional `workflow/envs/*.yaml` + optional `profiles/<env>/`); target
  Snakemake version (current stable 8.x; `snakemake -n` is the validation
  primitive); raw inputs are immutable.
- **Validation loop (core)** — after any rule generation/edit, run
  `scripts/validate-workflow.py` (which runs `snakemake -n --cores 1`); read
  the output, locate the failing rule, fix, retry; if `snakemake` is absent,
  fall back to the script's static-structure check and clearly warn that real
  validation requires installing snakemake.
- **References (load on demand)** — pointers to the seven files with the
  conditions under which each is read.
- **Rules** — never claim a workflow works without a passing dry-run (or an
  explicitly flagged static-only check); paste the real stderr in the
  conversation, do not paraphrase "it passed"; never copy snkmaker or snakemake
  source verbatim — write original guidance and cite docs by section; present
  inferred wildcard generalizations and let the user confirm before
  generalizing across samples; new samples are added in `config.yaml`, never by
  editing the Snakefile.

### `description` (trigger)

> Use when building or generating a Snakemake workflow (turn ad-hoc bash, a
> Jupyter notebook, or a described goal into a modular pipeline: Snakefile +
> config.yaml + workflow/rules/ + scripts/), or recovering a misbehaving run
> (rerun storms, "Code has changed", ProtectedOutputException, incomplete
> files, temp/protected outputs). Triggers on "Snakemake workflow", "turn my
> bash into a pipeline", "convert this notebook to Snakemake", "write a
> Snakefile", "Snakemake reruns everything", or "pipeline-maker". Validates
> with `snakemake -n` and corrects in a loop. Not for Nextflow or WDL.

(~95–105 tokens; tighten to ≤ 100 when writing SKILL.md.)

### references/

Each file is self-contained, loaded only when the current task reaches it.

- `bash-to-workflow.md` — snkmaker bash-mode methodology: classify important vs
  one-timer commands, extract I/O, infer rule names, detect composite
  opportunities, infer wildcard generalization, Make-rule alternative (pointer
  only). Load when Mode A input is bash.
- `notebook-to-workflow.md` — snkmaker notebook-mode methodology: Read/Write/
  Wildcards per cell, dependency-DAG construction (Read matched to nearest
  prior Write), Rule-vs-Script cascading constraint, prefix/suffix codegen,
  export Snakefile + `scripts/*.py`. Load when Mode A input is a notebook.
- `snakemake-rules-and-best-practices.md` — rule syntax (`input`/`output`/
  `log`/`params`/`resources`/`threads`/`shell`/`run`/`script`); wildcards and
  `wildcard_constraints`; `expand`/`multiext`; **output flags**
  `protected()`/`temp()`/`directory()`/`ancient()`/`touch()` and their
  non-obvious semantics (e.g., `directory()` uses `.snakemake_timestamp`;
  `temp()` is not a rerun trigger; shared outputs must not be `temp()`); shell
  brace-escaping (write `{{` to emit a literal `{` in a shell string, since single braces are Snakemake format placeholders), `:q` quoting, bash strict mode);
  `shell:` vs `run:` vs `script:`; standard resources (`mem`/`disk`/`runtime`/
  `tmpdir`/`mem_mb`); `--max-checksum-file-size` checksum-vs-mtime behavior.
  **`output:` must be concrete paths** (strings or `expand()`/`multiext()`);
  functions/lambdas are allowed only in `input:`/`params:`/`resources:` — a bare
  function ref or lambda in `output:` errors (`Only input files can be specified
  as functions`). Some output field names are reserved (e.g., `count`) → rename.
  Distilled from `docs/snakefiles/rules.rst`, rewritten. Load when writing or
  reviewing any rule.
- `modularization-and-config.md` — `workflow/rules/*.smk` per stage, `common.smk`
  for shared helper functions (e.g., a `get_vqsr_resource_args`-style builder),
  `config.yaml` + `configfile:`, `samples.tsv`, `module`/`use rule .*` /
  `include`, `snakedeploy` pointers, `pathvars`. Load when structuring the
  workflow into modules/config.
- `deployment.md` — conda envs (`workflow/envs/*.yaml`), Apptainer/containers,
  executor plugins (SLURM), `profiles/<env>/profile.yaml` (executor/jobs/cores/
  default-resources/set-threads/set-resources/set-scatter), precedence (CLI >
  workflow-profile > global). **Resource sizing & scatter**: `resources:
  mem_mb`/`runtime`; dynamic resources via `attempt`/`input.size_mb` callables;
  that some tools scale memory with `interval × samples + fixed overhead` (not
  just input size) → scatter finer and bump `mem_mb` rather than retry; the
  `--retries` + `attempt`-scaled mem pattern for OOM recovery. SLURM
  `squeue`/`sacct` polling belongs to `bioinfo-project-organization`'s `runall`,
  not here. **Profile is the authority layer**: a profile's `set-resources`
  overrides both the rule's `resources:` and `config.yaml` — when changing a
  rule's memory, edit BOTH `config.yaml` AND the profile, then verify the actual
  `mem_mb`/`-Xmx` a job would get via a dry-run (the WGS agent's config-only edit
  silently didn't apply; a running orchestrator caches config at start, so
  resource edits need a restart). GATK `--tmp-dir .` resolves to cwd (project
  root) and scatters `libgkl*`/`libtiled*`/`loader_*` temp files there — use an
  absolute scratch path (`resources: tmpdir=`). Track `profiles/` in git (per-rule
  memory budget is essential for full runs), even though it is gitignored by
  default. Load when the user asks about environments/cluster/cloud or a job OOMs.
- `rerun-and-metadata.md` — **the proactive state-management reference**
  (grounded in `persistence/__init__.py` + `settings/enums.py` + `cli.py`):
  the five `RerunTrigger`s (CODE = shell text / run source / script mtime;
  INPUT = input path set; PARAMS = non-derived params; SOFTWARE_ENV =
  conda/container/env-module hash; MTIME = input newer than output, checksum for
  ≤1MB inputs, `ancient()`/`directory()` overrides); default = all five;
  `--rerun-triggers` to select. The per-output metadata record (what is stored).
  Incomplete markers (marked at job `started`, cleared at `finished`;
  `incomplete()` = marker + file exists) and `--rerun-incomplete`/`--keep-
  incomplete`. `--cleanup-metadata FILE…` (`--cm`) removes the record AND the
  incomplete mark — use it on the **entire affected output subtree** to escape
  the stale-code trap; benign `WorkflowError: metadata was not present` is fine.
  `--list-changes`/`--list-input-changes`/`--list-params-changes` to diagnose
  before running. `--forcerun`/`--force`/`--forceall`. `--delete-temp-output`/
  `--delete-all-output` (always `--dry-run` first; skips `protected()`).
  `--consider-ancient`, `--drop-metadata`. The stale-code trap (editing shell
  text / a param / a conda env retroactively invalidates prior outputs → plan
  whole-subtree cleanup before resuming). Force-stop recovery (enumerate
  incomplete, classify, `--rerun-incomplete`, don't delete intermediates).
  Large-DAG dry-run (`--batch RULE=I/N` official, or a `--configfile` override
  collapsing scatter to validate shell rendering — `--config` CLI rejects dotted
  keys; `--rerun-triggers mtime` to focus). `workflow.source_path` from `params:`
  causes spurious reruns — avoid. Operational facts: `--rerun-triggers` and
  `--quiet` are `nargs='+'` in v9 and greedily eat following positional targets —
  put targets before them or use `--` to separate; a running orchestrator caches
  config at start, so resource edits need a restart to take effect; `temp()`
  outputs are deleted once consumed → a downstream re-run needs them regenerated
  (don't `temp()` outputs you might re-run against); orphan/stale orchestrators
  hold the directory lock (`kill -9` the PID, then `snakemake --unlock`);
  production runs often use `--rerun-triggers mtime input` to exclude the CODE
  trigger (accepting stale-code outputs as valid) — `--allowed-rules` is the
  wrong mechanism for rerun control; post-hoc in-place output edits should
  preserve mtime to avoid triggering downstream reruns. Load for any recovery
  task, or whenever the user edits an existing rule.
- `debugging.md` — reactive dry-run error diagnosis using the **real exception
  vocabulary**: `MissingInputException` (no rule produces an input / wildcard
  resolves to nothing), `MissingOutputException`, `AmbiguousRuleException`
  (multiple rules can produce the same output → constrain wildcards or set
  `ruleorder`), `WildcardError` (unconstrained/ambiguous wildcard), plus
  `WorkflowError` (broad — read the message) and runtime tool failures. For
  each: cause, the snakemake message shape, the fix. `ProtectedOutputException`,
  `IncompleteFilesException`, and "Code has changed" point to
  `rerun-and-metadata.md`. Log files in `.snakemake/log/`; `--skip-script-
  cleanup`; targeting a single output to shrink the DAG; `--debug`/PDB. CLI footguns:
  `--rerun-triggers`/`--quiet` are `nargs='+'` in v9 (eat following positional
  targets — put targets first or use `--`). A dry-run validates DAG/syntax but
  NOT runtime tool-argument semantics — multi-arg tool flags (e.g., GATK
  `--resource:label,key=… <vcf>`) need manual re-reading of tool docs. `--reason`
  is gone in v9 (rerun reasons are always shown).
  Distilled from `docs/snakefiles/debugging_workflows.rst` + source, rewritten.
  Load when a dry-run fails and the cause is non-obvious.

### Assets

Each asset is a drop-in skeleton Claude fills per task.

- `Snakefile.tmpl` — main entry: `configfile: "config.yaml"` plus
  `include: "workflow/rules/main.smk"` (with a comment pointing to the
  module-based `use rule .*` alternative in `modularization-and-config.md`).
- `config.yaml.tmpl` — `samples` list, `paths` (input/output dirs), `params`
  (threads, etc.); commented so the user adapts it; references a `samples.tsv`
  pattern for multi-sample workflows.
- `rule.tmpl` — single-rule skeleton with `input`, `output`, `log`, `params`,
  `shell` (redirecting to `{log}`), and placeholder tokens (`<NAME>`,
  `<INPUT>`, `<OUTPUT>`, `<WILDCARD>`, `<COMMAND>`).
- `workflow-rules.smk.tmpl` — a modular rule file with one wildcarded rule
  example (`{sample}.fastq → {sample}.bam`) showing the generalization pattern.
- `common.smk.tmpl` — a `common.smk` skeleton for shared helper functions used
  across stage rule files (e.g., a resource-arg builder, a path resolver), with
  one example function and a comment that pure logic belongs in `scripts/*.py`
  while rule-formatting helpers belong here. Mirrors the real
  `workflow/rules/common.smk` pattern.

### `scripts/validate-workflow.py`

A `# /// script` inline-dependency Python script runnable with `uv run`:

- Run `snakemake -n --cores 1` in the workflow directory; capture stdout and
  stderr; report pass/fail by exit code.
- Lightweight classification of the **real high-frequency exceptions** observed
  in the WGS session data into a one-line hint plus a pointer to the right
  reference: `ProtectedOutputException`, `IncompleteFilesException`, and
  "Code has changed" → `rerun-and-metadata.md`; `MissingInputException`,
  `MissingOutputException`, `AmbiguousRuleException`, `WildcardError` →
  `debugging.md`; `WorkflowError` → print the message verbatim (too broad to
  classify). **Print the full stderr unchanged** for Claude to read.
- If `snakemake` is not on `PATH`, fall back to a static-structure check:
  every rule has `output` and either `shell` or `run`; wildcards in `output`
  appear in `input` or are otherwise constrained; no duplicate rule names.
  Print an explicit warning that real validation requires snakemake.
- Exit 0 on pass, non-zero on fail. Called by Claude inside the validation
  loop; the script does not attempt fixes itself.

## Data flow

**Mode A · bash/notebook → workflow**

1. User provides bash commands (paste / file / history) or a notebook file.
2. Claude loads `bash-to-workflow.md` (or `notebook-to-workflow.md`):
   classifies commands, extracts I/O, infers rule names, identifies wildcard
   generalization and composite opportunities; for notebooks, resolves
   Read/Write/Wildcards, builds the dependency DAG, applies the Rule-vs-Script
   cascading constraint.
3. Claude presents the inferred rule list / DAG; judgment calls
   (generalization scope, rule-vs-script) are confirmed by the user.
4. Claude generates rules from `rule.tmpl` / `workflow-rules.smk.tmpl`, writes
   `Snakefile` (`Snakefile.tmpl`), `config.yaml` (`config.yaml.tmpl`), and
   `common.smk` (`common.smk.tmpl`) when shared helpers are needed; notebook
   path also writes `scripts/*.py` (prefix + suffix codegen).
5. Claude runs `validate-workflow.py`, reads the output, fixes, retries until
   dry-run passes.
6. Hands off to `bioinfo-project-organization` when project-level layout is
   needed.

**Mode B · from-scratch → workflow**

1. User describes the goal and the data manifest.
2. Claude loads `snakemake-rules-and-best-practices.md` +
   `modularization-and-config.md`; decomposes into steps naming tool / inputs /
   outputs / params; sketches the DAG and wildcard strategy.
3. Claude confirms the DAG with the user.
4. Claude generates the modular scaffold from assets and fills in the rules;
   optionally loads `deployment.md` to add conda envs / a SLURM profile.
5. Claude runs `validate-workflow.py` and runs the fix loop.
6. Hands off to the project-organization skill.

**Recovery** (any mode, existing workflow)

1. User reports a rerun storm, `ProtectedOutputException`, incomplete files
   after a crash, or disk bloat.
2. Claude loads `rerun-and-metadata.md`; runs `--list-changes` (or
   `--list-input-changes` / `--list-params-changes`) and/or a `--dry-run` to
   enumerate what is invalidated or incomplete.
3. Claude classifies: stale-code (data-valid outputs judged "Code has changed")
   vs genuinely-incomplete (force-stopped) vs disk-bloat (reclaimable temp).
4. Claude proposes the recovery command set (whole-subtree `--cleanup-metadata`,
   `--rerun-incomplete`, `--delete-temp-output` — always `--dry-run` first),
   confirms with the user, runs, and verifies no `ProtectedOutputException`
   remains and the dry-run is clean.

## Error handling

- Dry-run failure → read stderr, locate the failing rule, load `debugging.md`
  if the cause is non-obvious, fix, re-run.
- Stale-code rerun trap (`Code has changed` / `ProtectedOutputException` after
  editing a rule) → load `rerun-and-metadata.md`; `--cleanup-metadata` the
  entire affected output subtree (every output with a pre-change record), not
  just the obvious file; benign `WorkflowError: metadata was not present` for
  already-clean files is fine; verify with a `--dry-run` + `--rerun-incomplete`.
- Force-stop / `IncompleteFilesException` → dry-run to enumerate incomplete
  files (named in the exception), classify them as "to rebuild" (not
  "completed"), resume with `--rerun-incomplete`; do NOT delete their
  intermediates.
- `snakemake` missing → static-structure check passes with an explicit warning;
  the output is flagged "unvalidated, requires snakemake for real validation."
- Tool reproducibly crashes on valid input → do not loop retries; load
  `debugging.md`/`deployment.md`, substitute an equivalent, validate
  equivalence against the original.
- Ambiguous transformation (a command could be a rule or a script; wildcard
  generalization scope unclear) → present options to the user; do not guess
  silently.
- 2–3 failed fix attempts on the same error → stop, report the stderr and the
  suspected root cause; do not loop silently.
- Insufficient input (no commands, no goal, no data manifest) → ask for
  clarification before generating anything.
- "Done" is defined by a passing `snakemake -n`, never by "the command runs."

## Registration

1. Append `"./bioinformatics/pipeline-maker"` to the `bioinformatics` plugin's
   `skills` array in `.claude-plugin/marketplace.json`.
2. Add a row to the `bioinformatics` category table in `README.md` with a
   one-line description.
3. No new plugin install line needed — the `bioinformatics` plugin is already
   installable.

## Out of scope (v1)

- **Formal testing** — deferred to real-world use per the user; no local
  trigger-fixture or token-budget test harness is written as part of this
  skill. (The repo's `./count-skill-tokens.py` size check is still recommended
  once during authoring, but is not part of the skill itself.)
- **Other workflow engines** — Nextflow, WDL, Cromwell, Make-rule output
  (snkmaker supports GNU Make output; v1 is Snakemake-only).
- **Full project scaffolding** — `experiments/`, `runall`, `lab-notebook.md`,
  `artifacts/`, Git practices are owned by `bioinfo-project-organization`;
  this skill cross-references it and does not duplicate.
- **snkmaker's GUI-only features** — recording live terminal history, the
  VS Code webview, the `@snakemaker` / `@snakemaker-notebook` Copilot-chat
  assistants. The skill works conversationally from user-provided input
  instead.
- **A scaffold-generation helper script** — scaffolding is done by Claude
  with Bash + Write guided by the skill and the asset templates; a scaffold
  script would restate the skill's own instructions. The only script is
  `validate-workflow.py`, which is genuinely deterministic.
- **Domain-specific analysis-script gotchas** (MultiQC Picard collapse,
  bcftools-stats column indices, VQSR tranche layout, fastq-basename→sample-id
  mapping) — these belong in the domain analysis skills (e.g.,
  `population-genomics`), not the workflow-engineering skill. `pipeline-maker`
  only notes the general discipline: companion scripts go in tracked
  `scripts/`, and their data-source gotchas are the analysis skill's concern.
