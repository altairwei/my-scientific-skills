---
name: interactive-repl
description: Drive a persistent R or Python REPL so you can iterate in-session — load
  → transform → inspect → plot → fix — without re-running scripts from scratch each
  time. Use when the task involves iterating on data in R or Python, "keep a
  session open," "run this chunk," "what's in this dataframe." Triggers on
  pandas/tidyverse/ggplot/matplotlib. Do NOT use
  for batch pipelines or long-running jobs — use pipeline-maker there.
metadata:
  author: Altair Wei
  version: "0.1"
license: MIT
---

# Interactive REPL

A data scientist keeps one live session open per task — load data once, inspect,
fix assumptions, re-plot. Re-running a script from scratch each time you want to peek
wastes time and breaks the iterate-fast loop. This skill gives you a persistent
R/Python REPL via two MCP servers (`python-repl`, `r-repl`) so state survives across
calls.

## Setup — check, then fix (drive it yourself)

The REPL lives in MCP servers; you only have the tools (`run_code`, `run_chunk`,
`list_variables`, `worker_mode`, …) if the plugin that ships them is installed
**and** Claude Code loaded them. When the user asks to "set up this skill" or the
REPL tools are missing, **drive the setup yourself — diagnose and fix what you
can; hand the user only the steps that genuinely require them**. Do not reply
with a checklist of commands for the user to run.

1. **Tools present?** You see `run_code` / `session_info` / `worker_mode` →
   probe once (`session_info` on a throwaway session, or `worker_mode()` with
   no args) and you're set. Missing → continue.
2. **Dependencies — run the skill's one-shot installer yourself**:
   `scripts/setup.sh` (idempotent, safe to re-run). It installs `uv` if
   missing and installs ALL python runtime deps (`mcp pydantic numpy pandas
   matplotlib`) into the worker's `py-site` in a single `uv pip install
   --target` — no mid-session lazy-install stalls, and once cached it works
   offline. Report its output; fix anything it flags.
3. **R for r-repl — find a usable R** (on HPC it is usually NOT on PATH; see
   `references/r-setup.md` for the full discovery commands): `command -v
   Rscript`; `conda env list` then test candidates with `conda run -n <env>
   Rscript --version`; `module avail` for an R module. You need R **and** the
   `jsonlite` / `knitr` / `ggplot2` packages (check with `Rscript -e
   'rownames(installed.packages())'`). When you find one, configure the r-repl
   server with `INTERACTIVE_REPL_R_ENV` (conda env name) or
   `INTERACTIVE_REPL_R_BIN` (path to R) — persist it yourself (e.g. append the
   `export` to `~/.bashrc`) and tell the user to restart Claude Code, because
   the server reads these at launch. If no R exists anywhere, tell the user the
   one command to create it (`mamba create -n r-repl -c conda-forge r-base
   r-jsonlite r-knitr r-ggplot2`).
4. **Plugin state** — inspect `~/.claude/plugins/…` on disk: marketplace entry
   present? plugin enabled? If the plugin itself is missing, ask the user to
   run `/plugin install data-science@my-scientific-skills` (slash commands are
   user-only) — one command, nothing else.
5. **Loaded servers never appear mid-session** — MCP servers start once per
   Claude Code process. If deps and plugin are fine, the remaining user-only
   step is `/reload-plugins` or a restart. After the user acts, re-verify with
   `session_info` on both servers before claiming the REPL is usable.

When the user says "set up this skill", the outcome is a working probe on both
servers — or a precise one-step ask with everything else already done.

## The iterate rule

Once a session is started for a task, keep running code **in it**. Don't re-run a
one-shot script to peek at a result — state persists, use it. Re-importing and
re-loading each turn wastes tokens and time.

## When to use the REPL — and when not

Use it for stateful, multi-chunk, state-carrying analysis — load once, iterate across
many calls sharing DB connections and loaded frames. **Don't force it for one-shot
extraction** — for exploratory SQL+regex text-mining, batch pipelines, or long-running
jobs (training, big joins), use one-shot scripts / the `pipeline-maker` skill.

You don't need to call `start` — the first `run_code` auto-creates the named session.
Pick a session name matching the task (`lmp`, `infection`, …) and keep using it.

## Language choice

Match the surrounding project (pandas vs tidyverse — see the `exploratory-data-analysis`
skill). Route to `python-repl` or `r-repl` accordingly. Session names are scoped per
server: a `lmp` session on `python-repl` and on `r-repl` are independent.

## The tools (per server)

- `run_code(session, code)` — run code; returns `{stdout, stderr, error, plots:[path], truncated, degraded}`. State persists.
- `run_chunk(session, file, selector)` — run one chunk (or a range) from a `.Rmd`/`.qmd`/`.ipynb` notebook in the session. `selector` = label / index / `N-M` / `N-` / `^label` (run 1..label) / `label^` (run label..end). Routes by language; skips `eval=FALSE`. See `references/notebook-iteration.md`.
- `list_variables(session)` — variable summary (type/size/preview).
- `inspect_variable(session, name, path?)` — drill into a DataFrame's columns / a list's elements.
- `inject(session, path)` — exec a `kernel.py`/`kernel.R` sidecar into the namespace. Call once when another skill ships a sidecar.
- `restart(session)` — wipe + respawn the worker. **Rarely** — only after a crash or to deliberately reset (loses DB connections + loaded data).
- `session_info(session)` — versions, loaded packages, working dir, variable count, and (slurm mode) compute-node job id / node / transport.
- `worker_mode(mode?, slurm_flags?, transport?)` — probe or switch how workers launch: `local` (default) vs `slurm` (srun on a compute node). Call it with no args to detect the environment; switch for HPC work. See `references/slurm-hpc.md`.

## Plots — save and look (necessary, not sufficient)

`run_code` auto-saves figures (matplotlib → PNG; ggplot → `ggsave`) and returns paths.
**`Read` the PNG to actually see it.** But know you can `Read` a PNG and still
mis-reason: a real session attributed empty `scale_y_log10()` histogram panels to
"censored markers" when the true cause was `count=1` bars can't render 1→0 on log10
(`log(0)` undefined). Understand the **rendering semantics**, not just the data —
especially for log/tricky-scale plots. If the user says "the plot looks wrong," believe
them first, then look. Don't auto-"fix" because you saw a warning (`log(0)=-Inf` /
`Removed N rows` are normal). If `Read` returns "Unsupported Image," verify key
distribution stats numerically.

## R conventions

- Prefer `pkg::fun()` over `library()` (avoids attaching/clobbering).
- Prefer `scale_y_sqrt()` over `scale_y_log10()` to avoid the `count=1` down-fill artifact.
- Use absolute paths for `source()`/`read.csv()`/file args — the session's cwd may differ from yours.

## Multi-session discipline

One driver per session — don't interleave writes to the same named session from parallel
turns. Use distinct names for parallel tasks (`lmp`, `splitqc`, …).

## When to restart (rarely)

After a crash (`run_code` returns "worker died") → `restart(session)`, or to deliberately
reset. **Do not restart between chunks "to be safe"** — restart-cycles lose DB
connections and loaded data.

## HPC / Slurm — compute nodes

On supercomputing clusters, heavy compute must run on a compute node, not the
login node. `worker_mode()` on the server probes the environment
(`srun_available`, `already_in_allocation`, `ssh_available`) and switches
between `local` and `slurm` launch — call it before heavy work when the user
mentions clusters/queues/partitions. Slurm sessions are tied to the
allocation: expiry surfaces as `worker died` → `restart` resubmits (fresh
namespace). Requires shared storage for plots (`CLAUDE_PLUGIN_DATA`) — see
`references/slurm-hpc.md`.

## Ad-hoc inspection is first-class

`run_code` runs any code; use it freely for quick peeks (`_peek(df)`, `dim(df)`,
`head(df)`).

## Notebooks (.Rmd / .qmd / .ipynb)

For notebook workflows, don't hand-extract chunks — use the chunk tools. List chunks with
`notebook_chunks.py FILE` (no session), then `run_chunk(session, FILE, selector)` to run one
or a range in dependency order. Routes each chunk to the matching server by language (R →
`r-repl`, Python → `python-repl`); `eval=FALSE` chunks are skipped. Read-only on the file —
outputs to disk + `Read`. See `references/notebook-iteration.md` for the full workflow.

## Survives compaction

REPL state lives in the server process, outside your context window. If your context is
compacted mid-analysis, re-attach by session name + `list_variables` and recover — the
DB connections and loaded data are still there.

## Extensibility

When another active skill ships a `kernel.py`/`kernel.R`, call `inject(path)` once
before using its helpers. The base sidecar (`_peek`/`_who`/`_fig` in Python,
`peek`/`who`/`fig` in R) is auto-loaded at session start.

## Deep docs

Read on demand: `references/tools.md` (full API), `references/sidecar-authoring.md`
(how to write a sidecar for your skill), `references/r-setup.md` (conda env,
neutralized functions), `references/troubleshooting.md` (stuck code, missing deps,
worker crashes), `references/plot-iteration.md` (save-and-look, expanded),
`references/notebook-iteration.md` (`.Rmd`/`.qmd`/`.ipynb` chunk list + run),
`references/slurm-hpc.md` (HPC: run workers on compute nodes via srun).
