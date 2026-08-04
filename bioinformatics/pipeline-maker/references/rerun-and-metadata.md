# Rerun and metadata

The proactive state-management reference. Loaded for any recovery task, or whenever editing an existing rule on a workflow with completed outputs. Grounded in `external/snakemake/src/snakemake/persistence/__init__.py` + `settings/enums.py` + `cli.py` (cite by function, do not copy).

## The five rerun triggers

Enum `RerunTrigger` (`settings/enums.py`): `MTIME`, `PARAMS`, `INPUT`, `SOFTWARE_ENV`, `CODE`. Default = all five (guarantees results match the workflow code/config). `--rerun-triggers` selects a subset.

- **CODE** — compares the rule's shell text (`rule.shellcmd`) or run-block source (`rule.run_func_src`); for `script:`/`notebook:` rules, the script file's mtime. Source: `persistence/__init__.py` `_code()` (returns `rule.shellcmd` or `rule.run_func_src` or None). **This is the stale-code trap**: editing a rule's shell text retroactively invalidates every prior output of that rule. Adding `temp()`/`protected()` does NOT change `_code` → no rerun.
- **INPUT** — compares the sorted set of input file paths (`_input()`; pipe → `<pipe>`, service → `<service>`, storage query paths). Not input mtime — the input *path set* (adding/removing/renaming an input file triggers rerun).
- **PARAMS** — compares non-derived `params:` values (serialized via `_serialize_param`; pandas objects hashed). Derived params (computed from input/output) are captured by INPUT. Format-version gated (v6+). Changing a `params:` value reruns.
- **SOFTWARE_ENV** — conda env content hash / container image URL / env-modules hash (`_software_stack_hash()`).
- **MTIME** — an input file's mtime newer than the output's; for inputs ≤ 1 MB, checksum instead (only rerun if checksum changed). `ancient()` ignores mtime; `directory()` uses `.snakemake_timestamp`.

## The per-output metadata record

Stored under `.snakemake/metadata/` with a **base64-encoded path filename** — decode with `python3 -c "import base64,os; print(base64.b64decode(fn).decode())"` to map a record to its output path. Each record stores: `code`, `input`, `log`, `params`, `conda_env`, `software_stack_hash`, `container_img_url`, `input_checksums`, `endtime`, `starttime`, `rule`, `record_format_version`. To inspect why an output is judged stale, decode both its record and its inputs' records and compare. (Backend may be files or a sqlite db; `.snakemake/db.sqlite` if the latter.)

## Incomplete markers

`started(job)` marks all its outputs incomplete (`_mark_incomplete`). `finished(job)` writes the full record AND unmarks incomplete (or, with `--drop-metadata`, just unmarks). `incomplete(job)` returns outputs that are BOTH marked AND exist on disk. A force-stopped job leaves markers → `IncompleteFilesException` on the next run (the exception names the files). File presence ≠ completion.

## `--rerun-incomplete` (`--ri`)

Re-run all jobs whose output is marked incomplete (interrupted). Use after a force-stop. `--keep-incomplete` keeps incomplete output files from failed jobs (default deletes them).

## `--cleanup-metadata FILE…` (`--cm`)

`cleanup_metadata()` calls `_unmark_incomplete(key)` then `_delete_record(key)`: removes BOTH the incomplete marker AND the metadata record. Use it on the **entire affected output subtree** to escape the stale-code trap. **Build the cleanup list from files actually present on disk per sample's full output subtree** — every rule output with a pre-change record (~55 files per single-run sample in the WGS case: `unit{unit}/aligned.sorted.bam`, `dedup.bam{,.bai}`, `bqsr/interval*/recal.table`, `bqsr/recal.table`, `recalibrated/interval*/recal.bam`, `recalibrated.cram{,.crai}`). **The code-change source may be ANY commit on ANY rule** — the WGS agent missed `bwa_mem2_mem`'s `aligned.sorted.bam` because it only thought about GATK; bwa's `-@ 24→-@ 2` (a different commit) also fired "Code has changed". Use `git log -- <rulefile>` to find all commits touching a rule's shell text. Benign `WorkflowError: metadata was not present` for already-clean files is fine.

## Diagnose before running

- `--list-changes code|input|params` — list outputs whose code/input/params changed since creation.
- `--list-input-changes` / `--list-params-changes` — narrower variants.
- A `--dry-run` shows what would rerun and the reason (`Code has changed since last execution`, `Input files updated by another job`, `Newer`, `Forced execution`). In v9, `--reason` is gone — reasons are always shown.

## Forcing reruns

- `--forcerun RULE|FILE` (`-R`) — force re-execution of the given rules/files (use when you changed a rule and want all its output updated).
- `--force` (`-f`) — force the selected target/first rule regardless of existing output.
- `--forceall` (`-F`) — force the target + all dependencies.

## Reclaiming disk

- `--delete-temp-output` — delete all `temp()`-flagged outputs that exist on disk for the target subgraph; skips `protected()`. **Always `--dry-run` first** (lists what would be deleted). Does not recurse subworkflows. Does not need a job to run.
- `--delete-all-output` — delete all workflow outputs; skips write-protected files.
- Adding `temp()` to a rule does not auto-delete intermediates from prior runs — that's what `--delete-temp-output` is for. To reclaim, run `snakemake --delete-temp-output --dry-run <targets>` to preview, then without `--dry-run` to delete.

## `--consider-ancient` and `--drop-metadata`

- `--consider-ancient RULE=INPUTITEMS` — overrule the mtime trigger for known-stable inputs (e.g., a reference fasta that was re-touched but not changed). Put in a workflow profile to make it persistent.
- `--drop-metadata` — stop tracking metadata after jobs finish (faster, but disables CODE/PARAMS/SOFTWARE triggers — only mtime remains; `--list_*_changes` and `--report` become empty).

## Stale-code trap workflow

Before resuming after a rule edit:

1. `git log --oneline -- <rulefile>` to find all shell-text-changing commits since the outputs were made.
2. Build the cleanup list = every rule output in the affected samples' subtrees (cram/crai + every intermediate, **including BWA unit BAMs** — don't forget rules whose shell text changed in a different commit).
3. `snakemake --cleanup-metadata <all those paths>` (benign `metadata was not present` for already-clean files).
4. `snakemake --dry-run --rerun-incomplete <targets>` to verify: no `ProtectedOutputException`, `Code has changed` count = 0.
5. Resume.

Distinguish **stale-code** (data-valid outputs judged "Code has changed" — e.g., `-Xmx` only bounds the JVM heap, doesn't change results → `--cleanup-metadata` to accept) from **incomplete** (force-stopped, the output is untrusted → `--rerun-incomplete` to rebuild). An interrupted final output (e.g., a cram written but its `.crai` missing) is untrusted and must be rebuilt.

## Force-stop recovery

Dry-run to enumerate incomplete files (named in `IncompleteFilesException`); classify them as "to rebuild" (not "completed"); resume with `--rerun-incomplete`; do not delete their intermediates. Watch for interrupted final outputs (cram written, `.crai` missing) — these are untrusted.

## Large-DAG dry-run

- `--batch RULE=I/N` — official batching; only build the I-th batch of `RULE`'s inputs. Good for huge cohorts.
- A `--configfile /tmp/override.yaml` collapsing scatter (e.g., `bqsr: {scatter_intervals: 1}`) validates that all rule shells render without building the full DAG. `--config` CLI rejects dotted keys — use a `--configfile` override.
- `--rerun-triggers mtime` to focus the dry-run on mtime only.
- Large-cohort dry-runs time out on shared filesystems (DAG build >8 min for 529 samples × ~60 jobs). Use single-sample dry-runs as safety checks first: `snakemake -n --cores 1 results/<sample>/final.output`.

## CLI `nargs='+'` footguns

`--rerun-triggers` and `--quiet` are `nargs='+'` in v9 and greedily eat following positional targets → `snakemake --dry-run --rerun-triggers mtime input results/foo.bam` fails because `results/foo.bam` is consumed as another trigger value. Put targets BEFORE these flags, or use `--` to separate: `snakemake -n --cores 1 results/foo.bam --rerun-triggers mtime input`, or `snakemake -n --cores 1 --rerun-triggers mtime input -- results/foo.bam`.

## Running orchestrator caches config

A running snakemake orchestrator caches `config.yaml` at start; resource edits need a **restart** to take effect. (The WGS agent changed `genotypegvcfs_mem_mb` from 24 GB to 40 GB mid-run; the running orchestrator kept using 24 GB.)

## `temp()` outputs are deleted once consumed

A `temp()` output is deleted after its last consumer finishes. A downstream re-run that needs it will trigger regeneration — including all upstream jobs up to that intermediate. Don't `temp()` outputs you might re-run against unless regeneration is cheap. (In the WGS pipeline, `temp()`-ing the GVCFs meant a failed `genotypegvcfs` retry had to re-run `haplotypecaller` for that interval.)

## Stale locks

Orphan/stale orchestrators hold the directory lock → `LockException: Directory cannot be locked` for new runs. `kill -9 <pid>` the orphan (check `pgrep -af snakemake`), then `snakemake --unlock` to remove the stale lock. A long dry-run can use `--nolock` to avoid holding the lock.

## Post-hoc in-place output edits

When converting an output format in place (e.g., CRAM 3.1 → 3.0 for GATK compatibility), preserve the mtime (`samtools ... && touch -r <reference> <new>`) so `--rerun-triggers mtime input` doesn't trigger downstream reruns. Use `--rerun-triggers mtime input` (excluding CODE) on the production run to accept such edits.

## `workflow.source_path` from `params:` causes spurious reruns

`workflow.source_path` returns a cached path that may change between runs; use it only from `input:`, never from `params:` (it would trigger spurious reruns there).

## Production discipline: `--rerun-triggers mtime input`

Production runs often use `--rerun-triggers mtime input` to exclude the CODE trigger — accepting stale-code outputs as valid (the trade-off: a real code change won't trigger reruns either, so use this only when you trust the existing outputs). `--allowed-rules` is the WRONG mechanism for rerun control — it filters which rules can run, not what invalidates them.
