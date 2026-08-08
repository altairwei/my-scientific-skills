# Debugging

Loaded when a dry-run fails and the cause is non-obvious. Reactive diagnosis using the **real exception vocabulary** observed in the WGS session. Distilled from `external/snakemake/docs/snakefiles/debugging_workflows.rst` + source (rewritten). For each: cause, the message shape, the fix.

## Exception vocabulary

- **`MissingInputException`** — no rule produces a requested input, or a wildcard resolved to nothing. Message lists the missing input files. Fix: add a producer rule, fix the input path/wildcard, or mark the file `ancient()`/provide it externally.
- **`MissingOutputException`** — a rule finished but a declared output is missing. Fix: check the rule's command actually writes the declared path (common causes: typo in the output path, the command writes elsewhere, or the job was killed mid-write).
- **`AmbiguousRuleException`** — multiple rules can produce the same output. Fix: constrain wildcards (`wildcard_constraints`), add `ruleorder: a > b`, or make rule outputs disjoint.
- **`WildcardError`** — unconstrained or ambiguous wildcard (e.g., `{a}.{b}.txt` matching `1.2.3.txt`). Fix: `wildcard_constraints` with regexes.
- **`WorkflowError`** — broad; read the message. Common sub-cases:
  - `metadata was not present` — benign after `--cleanup-metadata` (the record was already gone); ignore.
  - `Directory cannot be locked` — a stale/orchestrator lock; see `rerun-and-metadata.md` (kill the orphan, `snakemake --unlock`).
  - `MissingRuleException` — usually a path-construction bug in your own command (e.g., a doubled path component like `results/alignment/results/alignment/...`); check your `CRAMS=$(...)` builder.

## `ProtectedOutputException` / `IncompleteFilesException` / "Code has changed"

These point to `rerun-and-metadata.md`. Note: `ProtectedOutputException` is thrown **before** DAG construction (with `--rerun-incomplete` on a protected output that needs rerun), so no `reason` detail is shown. To capture the reason, temporarily `chmod u+w` the protected output, dry-run to read the reason, then re-protect (or leave it unprotected if you intend to rebuild it).

## CLI invocation footguns

- `--rerun-triggers` and `--quiet` are `nargs='+'` in v9 — they greedily eat following positional targets. Put targets **before** these flags or use `--` to separate. (The WGS agent hit this 3+ times.)
- `--reason` is gone in v9 — rerun reasons are always shown.

## A dry-run validates DAG/syntax, not runtime tool semantics

A dry-run confirms the DAG builds and shells render, but it does **not** execute the commands, so it cannot catch runtime tool-argument bugs. Multi-arg tool flags need manual re-reading of tool docs. Example: GATK `--resource` requires the label paired with the VCF as the **next** argument (`--resource:hapmap,key=... hapmap.vcf`), not a bare label. Re-read your rules for multi-arg tool flags before declaring done.

## Tool reproducibly crashes on valid input

Do not loop retries. Reproduce on a small slice (proves it's not scale-related), then substitute an equivalent and **validate equivalence** against the original before declaring success. Example: `vcftools --TsTv-by-count` glibc-heap-corrupted on multiallelic + `*` alleles with `Number=A` INFO fields — replaced with `bcftools query -f '%REF\t%ALT\t%AC\n' | awk -f workflow/scripts/tstv_by_count.awk`, validated 938/938 bins identical to vcftools.

## Where are the logs (find them before guessing)

When a job fails, logs live in three places — check them in this order:

1. **The rule's own `log:` files — first place to look.** Every rule declares `log: "logs/..."`; the rule's command is expected to redirect output there (`> {log} 2>&1`). **Snakemake never deletes log files on failure** — that is their purpose. To find them: read the failing rule's `log:` directive (e.g., `logs/{sample}/<rule>.log`), or `find logs -name "*.log"`. Runs often write rule logs under a timestamped directory (in the WGS pipeline: `logs/<YYYYMMDD_HHMMSS>/<rule>/<file>.log`).
2. **The main snakemake process log — for workflow-level problems.** `.snakemake/log/<timestamp>.<runid>.snakemake.log`, one per run, mirroring the console. Find the latest with `ls -t .snakemake/log/*.snakemake.log | head -1`. Essential when the run was non-interactive (background orchestrator, cluster job, container). The debug flow greps it for `Error in rule`, `SLURM status is: '...'`, `Traceback`, `WorkflowError`.
3. **Executor-plugin (SLURM/HPC) job logs — for scheduler-level verdicts.** The slurm executor plugin writes per-job submission output to a directory configured in the profile/plugin settings (in the WGS pipeline: `logs/slurm/rule_<rulename>/<jobid>.log`, via `{rule}`/`{jobid}` placeholders) — **read the profile to find the configured location**. When the rule's own log is empty or clean, the SLURM job log carries the scheduler verdict: `OUT_OF_MEMORY`, `TIME_LIMIT`, exit codes. Also check the rendered jobscript (the plugin writes it under `.snakemake/`) to see exactly what was submitted, and `sacct -j <jobid>` for the scheduler state.
4. **Make the failure visible.** `--show-failed-logs` automatically displays the logs of failed jobs at the end of the run; `--printshellcmds` (`-p`) prints the exact shell command each job ran — confirming what actually executed (e.g., whether a `-Xmx`/`mem_mb` change reached the job).

## Other debugging aids

- `--skip-script-cleanup` — keep wrapper scripts for `script:` rules (default location `.snakemake/scripts/`); inspect what Snakemake actually invoked.
- Target a single output to shrink the DAG: `snakemake path/to/output.file <args>` (put the target first to avoid `nargs='+'` eating it).
- `--debug` — drop into PDB for `run:` blocks and Python scripts.
- `--nolock` — don't hold the directory lock during a long dry-run (so the user can run real things meanwhile).
- For `script:` rules, redirect stderr into `{log}` from inside the script (Python: `sys.stderr = open(snakemake.log[0], "w", buffering=1)`; R: `sink(file(snakemake@log[[1]]))`).

## `du` on subtrees with hardlinks overcounts

When measuring reclaimable space, `du -sk` on a subtree with hardlinks/shared paths double-counts and reports nonsense (the WGS agent saw 54 PB for 348 samples whose real footprint was ~41 TB). Sum reclaimable space from the `--delete-temp-output --dry-run` preview list directly, with dedup, instead of trusting `du` on the subtree.
