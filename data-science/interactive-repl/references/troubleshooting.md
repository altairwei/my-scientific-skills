# Troubleshooting — interactive-repl

## "worker died" / "R worker died"

The worker subprocess crashed (a segfault from a C extension, or R exited). The MCP
server survives — call `restart(session)` and continue. Stdio MCP servers are not
auto-restarted by Claude Code, but the *worker* (subprocess) is restartable; the server
process itself rarely crashes because all user code runs in the worker.

## Long-running code

`run_code` has its own `timeout` (default 300s, advisory in v1) — Claude Code's Bash
timeout does **not** apply to MCP tool calls. Very long jobs (training, big joins) are
not what the REPL is for — use one-shot scripts / `pipeline-maker`. If you must run a
long cell, chunk it so each `run_code` returns within reason.

## `browser()` / `readline()` / `scan()` blocks

R code that prompts for interactive input (`browser()`, `readline()`, `scan()` with no
input) blocks the worker — the cell won't return until timeout. Avoid these in REPL
code; they're for interactive RStudio sessions. The `dt_table`→`kable` neutralization
(see `r-setup.md`) covers the common `viewer()`/DT case.

## Dependency-ordering errors are expected, not bugs

`object 'X' not found` after a cell means a prior chunk that defines `X` hasn't run
yet. tryCatch catches it cleanly; the response returns with `error` set; the session
stays usable. Run chunks in dependency order (use `list_variables` to check what's
defined).

## Missing dependencies

- `uv` not installed — or `MCP server failed to start` / `ModuleNotFoundError: No module
  named 'mcp'` — → install `uv` (one line): `curl -LsSf https://astral.sh/uv/install.sh | sh`,
  then **restart Claude Code** so the servers pick up `uv` on `PATH`. The `data-science`
  plugin's MCP servers launch via `uv run`, which reads each server's `# /// script`
  metadata and auto-installs `mcp`/`pydantic`/… into an ephemeral env — so once `uv` exists,
  no further `pip install` is needed.
- R / `jsonlite` missing → see `r-setup.md`.

## MCP tools missing from the agent's toolset

If `run_code` / `list_variables` / `worker_mode` etc. never appear as available
tools, the `data-science` plugin's MCP servers are not loaded. Enable them:
`/plugin install data-science@my-scientific-skills`, then `/reload-plugins`
(restart Claude Code if the tools still don't appear — MCP servers start once
per Claude Code process). The servers launch via `uv`; if you see "MCP server
failed to start", install `uv` first (above) and restart. `r-repl` additionally
needs R installed (`r-setup.md`).

## First `import pandas` / `matplotlib` is slow (one-time, then cached)

The `python-repl` server starts with only `mcp`+`pydantic` installed (so MCP startup
stays fast and never times out). The heavy data-science deps (`numpy`, `matplotlib`,
`pandas`) are fetched **on first import** by the worker into a persistent
`${CLAUDE_PLUGIN_DATA}/py-site` dir via `uv pip install --target` (reuses `uv`'s wheel
cache). So the first `import pandas` in a session takes a few seconds (one-time); after
that it's instant, and later sessions reuse `py-site`. Only packages you actually import
are fetched — no plotting, no `matplotlib`.

## Context compaction mid-analysis

If your context window is compacted, the REPL state is **not** lost — it lives in the
server process, outside your context. Re-attach by session name: call
`list_variables(session)` to see what's still loaded, then continue. DB connections and
big data frames survive compaction (this is a key advantage over one-shot scripts).

## Restart-cycles lose state

Don't restart between chunks "to be safe" — each `restart` wipes DB connections and
loaded data. Only restart after a crash or to deliberately reset for a fresh analysis.

## Slurm / HPC

- `srun allocation did not start within Ns` — flags wrong (bad partition/account)
  or the queue is busy. Check `squeue`, fix `INTERACTIVE_REPL_SLURM`, retry.
- `worker died` after a slurm session started — the allocation expired or was
  preempted; `restart(session)` resubmits (fresh namespace — re-run the setup).
- Tunnel mode fails at session start — ssh from the compute node to the login
  node must be passwordless (`ssh login-node` with no prompt).
- Plots from a compute-node session are missing — `CLAUDE_PLUGIN_DATA` points
  at per-node storage; export it to shared storage (see `slurm-hpc.md`).
