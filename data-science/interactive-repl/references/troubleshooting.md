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

- `uv` not installed → install `uv` (the servers bootstrap via `uv run`).
- `mcp` / `pydantic` not installed → `uv run` auto-installs them (declared in each
  server's `# /// script` metadata).
- R / `jsonlite` missing → see `r-setup.md`.

## Context compaction mid-analysis

If your context window is compacted, the REPL state is **not** lost — it lives in the
server process, outside your context. Re-attach by session name: call
`list_variables(session)` to see what's still loaded, then continue. DB connections and
big data frames survive compaction (this is a key advantage over one-shot scripts).

## Restart-cycles lose state

Don't restart between chunks "to be safe" — each `restart` wipes DB connections and
loaded data. Only restart after a crash or to deliberately reset for a fresh analysis.
