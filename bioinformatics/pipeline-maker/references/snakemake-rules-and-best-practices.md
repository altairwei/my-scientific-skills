# Snakemake rules and best practices

Loaded when writing or reviewing any rule's syntax. Distilled from `external/snakemake/docs/snakefiles/rules.rst` (rewritten — cite by section, do not copy). Verify against the *installed* version before relying on a feature.

## Rule anatomy

A rule is `name`, `input`, `output`, `log`, `params`, `resources`, `threads`, and one of `shell` / `run` / `script`. Inside `shell`, `{input}`/`{output}`/`{log}`/`{params}`/`{wildcards}`/`{threads}` are format placeholders resolved at job time. Add `:q` to quote elements with whitespace: `{input:q}`. Snakemake runs `shell:` in bash strict mode (`set -euo pipefail`-ish) by default.

## Wildcards

A wildcard in an output pattern (`{sample}.bam`) is auto-resolved when a downstream rule requests a matching file; the resolved value propagates to input and to the `wildcards` object. Wildcard names in input and output must match. Ambiguity (`{a}.{b}.txt` matching `1.2.3.txt`) is resolved by constraining with regex: `wildcard_constraints: sample="\d+"` (rule-level) or a global `wildcard_constraints:` block. Prefer constraints over leaving wildcards loose.

## Aggregation helpers

- `expand("{s}.txt", s=SAMPLES)` — resolves at parse time (NOT a wildcard); the standard way to fan out over samples in `input:`.
- `multiext("plot", ".pdf", ".png")` — multiple outputs differing by extension; the only way to use between-workflow caching for multi-output rules.
- `collect()` is an alias for `expand()` (reads better for "collecting upstream files").
- `lookup("col == '{sample}'", within=df)` — look up a value in a pandas frame/dict by wildcard; combine with `expand`/`collect` and `branch`.

## Output flags and their non-obvious semantics

- `protected("f")` — write-protected (chmod read-only) after the rule completes. This is why stale-code reruns hit `ProtectedOutputException`: Snakemake cannot overwrite it.
- `temp("f")` — deleted after all consumers finish. `temp("f", group_jobs=True)` (Snakemake 9) auto-groups the creator and consumer onto one node. **`temp()` is NOT a rerun trigger** — the CODE trigger compares only `rule.shellcmd`/`run_func_src`, never output flags (verified in `persistence/__init__.py` `_code`). Adding `temp()` does not delete intermediates from prior runs — use `--delete-temp-output`. Mark shared outputs (e.g., an intervals BED used by all samples) as plain outputs, **never `temp()`** (it would be deleted mid-cohort). Don't `temp()` outputs you might need to re-run downstream against — they're deleted once consumed.
- `directory("d")` — explicit directory output; creates a `.snakemake_timestamp` file whose mtime is used for up-to-date checks (avoids directory-mtime churn from `.DS_Store`/`thumbs.db`). The directory is deleted before the job runs — other jobs must not write into it.
- `ancient("f")` — input mtime ignored, assumed older than any output; prevents rerun on input mtime change.
- `touch("f")` — Snakemake touches (creates/updates) the file after the command succeeds; for sentinel/done files.

## `output:` must be concrete paths

`output:` accepts strings, `expand()`/`multiext()` results, or called helpers returning strings. **Functions and lambdas are allowed only in `input:`/`params:`/`resources:`** — a bare function reference or a lambda in `output:` errors with `Only input files can be specified as functions`. If you need a computed output path, compute it at parse time into a module constant and `expand()` it, or call the helper in the output (`get_log_path(wildcards, "rule")`, not `get_log_path`).

## Reserved output field names

Some names are reserved by Snakemake — `count` is one (using `output: count=...` fails at parse). If a dry-run rejects an output field name, rename it.

## Verify a flag/helper exists before use

`optional()` is **not** a built-in output wrapper — assuming it exists causes a `NameError` at parse. Before relying on any flag or helper, confirm it exists in the installed version: `rg -n "def optional" "$(python -c 'import snakemake,os;print(os.path.dirname(snakemake.__file__))')/io_flags.py"` or check the vendored source. `update()`/`branch()`/`from_queue()`/`exists()`/`--executor touch` need Snakemake 9+.

## Shell brace-escaping

Single braces are Snakemake format placeholders. To emit a literal `{` in a shell string — e.g., a bash variable `${gendb_path}` — write `{{` so it renders as `{`: `"gendb://${{gendb_path}}"`. To show `{input}` literally inside a comment, mask it as `{{input}}` (Snakemake evaluates placeholders even in comments).

## `shell:` vs `run:` vs `script:`

- `shell:` — one-liner; bash strict mode; `{input}` etc. as placeholders.
- `run:` — a few lines of Python; access `input`/`output`/`wildcards`/`params`/`log`/`threads`/`resources`/`config` directly; keep it short, else use `script:`.
- `script:` — points to `scripts/*.{py,R,Rmd,jl,rs,sh,xsh,hy}`; the path is relative to the Snakefile (not the cwd). Inside the script, a `snakemake` object gives the same data (`snakemake.input[0]` in Python; `snakemake@input[[1]]` in R, 1-indexed; same in Julia/Rust). Bash scripts use associative arrays (`${snakemake_input[reference]}`) and require bash ≥ 4.

## Standard resources

`mem`/`disk`/`runtime`/`tmpdir` (strings with units: `"24 GB"`, `"2h"`) or `mem_mb`/`disk_mb` (ints); `runtime` as minutes-int or a string span; `tmpdir` sets `$TMPDIR`; `gpu`/`gpu_manufacturer`/`gpu_model`. Resources are **totals per job**, not per thread. Default-resources formula: `mem_mb=min(max(2*input.size_mb, 1000), 8000)`, `disk_mb=max(2*input.size_mb, 1000) if input else 50000`, `tmpdir=system_tmpdir`. Dynamic resources: callables `callable(wildcards[, input, threads, attempt])` — use `attempt` to scale mem on retry (`--retries N`). Resource scopes: `mem_mb`/`disk_mb`/`threads` are local-per-submission by default; others global.

## Checksum-vs-mtime

For input files ≤ 1 MB (default, `--max-checksum-file-size`), Snakemake records and compares checksums and only reruns if the checksum changed — even if the input mtime is newer. For larger inputs, mtime comparison. `ancient()` overrides (ignore mtime); `directory()` uses `.snakemake_timestamp`. This is why touching a small input without changing its content does not rerun, but rewriting a large one does.

## Best practices

- Use the `log:` directive on every rule — log files survive failures (Snakemake does not delete them on error), so you can read the cause.
- Put per-rule software in `conda:`/`container:` directives (see `deployment.md`).
- Name inputs/outputs (`input: reads=["{s}_R1.fq", "{s}_R2.fq"], ref="ref.fa"`) for readable shell strings.
- Prefer `expand()`/`multiext()` and parse-time constants over input functions when the file set is static; use input functions only when the set depends on wildcards in non-trivial ways.
