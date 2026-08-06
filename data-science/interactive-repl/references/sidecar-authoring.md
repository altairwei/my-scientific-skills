# Authoring a kernel.py / kernel.R sidecar

A sidecar is a file of helper functions that another skill injects into a running REPL
session via the `inject(session, path)` tool. The base skill (`interactive-repl`) ships
its own sidecar (`scripts/kernel.py`, `scripts/kernel.R`) — use it as a reference.

## Rules

1. **Top-level definitions only.** No code that runs at load (no `print()`, no
   `library()`, no DB connection, no `x <- ...` at top level). Define functions and
   constants only. Side-effect code runs once at `inject` time and is hard to debug.

2. **All non-stdlib imports inside function bodies** (lazy). This keeps `inject` fast
   and lets the sidecar load even when heavy deps (pandas, ggplot2) aren't installed —
   the import fails only when the specific helper is called.

   ```python
   # kernel.py — GOOD
   def profile_column(df, col):
       import pandas as pd   # lazy
       return df[col].describe()
   ```

   ```r
   # kernel.R — GOOD
   profile_col <- function(df, col) {
     # no library() at top level; use pkg::fun inside
     summary(df[[col]])
   }
   ```

3. **Prefix helpers** to avoid clobbering the user's namespace (e.g. `eda_`, `lmp_`).

4. **No `library()` in R sidecars** — the project forbids it (attaches and clobbers).
   Use `pkg::fun()`.

## Wiring

In your skill's `SKILL.md`, instruct the agent:

> After starting the REPL, call `inject("session", "<path>/kernel.py")` once before
> using these helpers.

The agent calls `inject` once per session; the sidecar's functions then live in the
namespace alongside the user's variables and the base `_peek`/`_who`/`_fig` (Python) or
`peek`/`who`/`fig` (R) helpers.

## Example

See `scripts/kernel.py` and `scripts/kernel.R` in this skill — they're auto-injected at
session start and double as the reference example.
