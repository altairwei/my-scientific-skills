# Interactive REPL Skill — Design Spec

**Date:** 2026-08-05
**Status:** Design — pending implementation plan
**Skill name:** `interactive-repl`
**Category:** `data-science/`

---

## 1. Problem & goal

A data scientist working in R or Python keeps one live session open per task — load data once, inspect variables, fix an assumption, re-plot. The agent today re-runs a script from scratch each time it wants to peek at a result: re-import, re-load, recompute. This is slow, token-expensive, and breaks the iterate-fast behavior that makes interactive data analysis work.

**Goal:** a *foundation* skill that teaches the agent to open and drive a persistent R/Python REPL via two MCP servers, ship convenience helpers that reduce cognitive load, and obey the behavioral rule *iterate in-session, don't re-run from scratch*. Other skills (EDA, population-genomics, …) build on top by injecting their own helpers.

## 2. The pivotal decision: MCP route (and the tool-agnostic departure)

The repo's prior convention is that skills are tool-agnostic (Bash/Read/Write only) and portable across agent platforms. **This skill deliberately departs from that convention**, because:

- A persistent REPL needs a long-lived process holding state in memory — exactly what an MCP server is. Claude Code plugins natively bundle MCP servers (auto-started on plugin enable, lifecycle tied to the plugin, `${CLAUDE_PLUGIN_ROOT}`/`${CLAUDE_PLUGIN_DATA}` for portable paths).
- The alternative — a Bash background process — cannot re-attach stdin, so it requires socket/file IPC the agent must hand-write each turn (fragile, token-expensive), and background tasks die in non-interactive mode.
- The MCP server process *is* the persistent REPL's driver; tool calls are clean request/response; output can be capped/summarized to fit MCP's token limit.
- **REPL state lives outside the agent's context window**, so it survives agent-context compaction. A real session (2df72e87) hit `Compacted` and the user re-issued the same request ~8× because in-context state was lost. With the MCP server holding state, the agent re-attaches by session name + `list_variables` and recovers — compaction no longer sinks the analysis.

**Trade-off accepted:** this skill is Claude-Code-specific (it will not work in Copilot CLI / Gemini CLI). Other skills in the repo remain tool-agnostic; only this one ships an MCP server. The skill does **not** reference openclaw-science or any external plugin — it is self-contained, crediting patterns only in this design doc, not in the shipped `SKILL.md`.

## 3. Goals & non-goals

**Goals (v1):**
- Persistent R and Python REPL via two MCP servers, one per language.
- Variables, imports, and loaded data persist across calls (within a named session).
- Convenience helpers: auto-summary of any variable, variable listing, plot capture, pandas-display config, matplotlib/`plt.show()` neutralization, R interactive-function neutralization.
- Named multi-session per language (one worker per task).
- Extensibility: other skills inject helper sidecars into the namespace.
- Behavioral guidance that shifts the agent from one-shot scripts to in-session iteration.

**Non-goals (deferred — see §18):** a control-plane/data-plane kernel split (the agent is the control plane), `host.llm` fan-out from the kernel, `host.view_image` crop boxes, per-cell interrupt, live stdout streaming mid-call, multi-session cross-language state, a Jupyter/IRkernel dependency.

## 4. Skill identity & placement

- **Name:** `interactive-repl`. The user's phrase was "interactive data analysis," but the foundation scope is *drive a persistent REPL + helpers + iterate-behavior*; `interactive-repl` reads truer to what the skill does. The `description` frontmatter carries the data-analysis trigger phrasing.
- **Location:** `data-science/interactive-repl/`.
- **Cross-category:** the `mcpServers` are scoped to the `data-science` plugin entry only. Bioinformatics skills that want the REPL either install the `data-science` plugin too, or — preferred — opt in via the sidecar-injection mechanism (ship a `kernel.py`/`kernel.R` and `inject` it into a running session). The `bioinformatics` marketplace entry gets **no** `mcpServers` (those skills don't universally need a REPL).

## 5. Plugin packaging & MCP wiring

Add `mcpServers` **inline** to the `data-science` entry in `.claude-plugin/marketplace.json`. With `strict: false`, the entry is the full component definition, so inline `mcpServers` scope the servers to *only* this plugin — a root `.mcp.json` is deliberately avoided (it would leak the servers to the `bioinformatics` and `scientific-writing` entries that share `source: "./"`).

```json
{
  "name": "data-science",
  "description": "Skills for data analysis, statistics, and visualization",
  "source": "./",
  "strict": false,
  "skills": [
    "./data-science/exploratory-data-analysis",
    "./data-science/interactive-repl"
  ],
  "mcpServers": {
    "python-repl": {
      "command": "uv",
      "args": ["run", "${CLAUDE_PLUGIN_ROOT}/data-science/interactive-repl/scripts/python_repl_server.py"]
    },
    "r-repl": {
      "command": "uv",
      "args": ["run", "${CLAUDE_PLUGIN_ROOT}/data-science/interactive-repl/scripts/r_repl_server.py"]
    }
  }
}
```

- Both servers bootstrap via `uv run`; each server script has inline `# /// script` metadata declaring the `mcp` SDK dependency, auto-installed on first run.
- `${CLAUDE_PLUGIN_ROOT}` resolves to the cached repo-root copy; `${CLAUDE_PLUGIN_DATA}` holds the persistent plots directory (survives plugin updates).
- Servers start eagerly when the data-science plugin is enabled (CLI has no lazy-start). A 30-min idle timeout reaps idle servers. **Stdio MCP servers are not auto-restarted on crash** — the skill handles restart (§13).

## 6. Architecture overview

```
┌──────────────────────────────────────────────────────────────────┐
│  Agent (Claude Code)                                             │
│   calls mcp__data-science_python-repl__* / mcp__..._r-repl__*    │
└────────────┬─────────────────────────────────────────────────────┘
             │ MCP stdio
┌────────────▼─────────────────────┐  ┌─────────────────────────────┐
│  python_repl_server.py           │  │  r_repl_server.py            │
│  (Python, mcp SDK; uv run)       │  │  (Python, mcp SDK; uv run)  │
│  - tool surface (§8)             │  │  - tool surface (§8)         │
│  - session pool: name→worker     │  │  - session pool: name→worker │
│  - auto-start on first run_code  │  │  - auto-start on first run   │
│  - proxies to worker over JSON   │  │  - proxies to worker over    │
│    lines on stdin/stdout         │  │    JSON over a Unix socket   │
└────────────┬─────────────────────┘  └────────────┬────────────────┘
             │ spawn                                   │ spawn
┌────────────▼─────────────────────┐  ┌──────────────▼────────────────┐
│  python_worker.py                │  │  repl.R (R --no-save)         │
│  (≈ wisp-science kernel_worker)  │  │  - withVisible+eval in        │
│  - namespace dict                │  │    globalenv, parse loop      │
│  - exec/eval heuristic           │  │  - auto ggsave on ggplot      │
│  - auto savefig on matplotlib    │  │  - neutralize interactive fns │
│  - MPLBACKEND=Agg, plt.show noop │  │  - tryCatch guarantees resp.  │
│  - tryCatch/never-empty          │  │  - never-empty/degraded output│
└──────────────────────────────────┘  └───────────────────────────────┘
```

**Subprocess isolation (deliberate):** each MCP server spawns worker subprocess(es) and proxies to them. A worker crash (e.g. a C-extension segfault) kills only the worker; the MCP server survives and restarts it — the MCP connection stays up. This mirrors wisp-science (a separate `kernel_worker.py` subprocess) and the user's `r-cell.sh` (R in a separate tmux session, driven by bash).

## 7. The two servers & their workers

**`python-repl` server** (`scripts/python_repl_server.py`): a Python stdio MCP server using the `mcp` SDK. Maintains a `session_name → worker_process` pool. Spawns `python_worker.py` per named session (lazy on first `run_code`). Proxies tool calls to the worker over JSON-per-line stdin/stdout.

**`python_worker.py`**: the namespace holder — patterned on wisp-science's `kernel_worker.py`. Holds a namespace dict `{"__name__":"__main__", "__builtins__":…}`. On init: `MPLBACKEND=Agg` (env, before any matplotlib import); monkeypatch `builtins.__import__` so `import pandas` triggers `_configure_pandas()` and `import matplotlib` triggers `_neutralize_pyplot_show()` (lazy, on first import); pre-import stdlib (`json,math,os,re,sys`) + lazy `numpy`/`pandas`. eval/exec heuristic (single expression → eval + print repr, like a notebook; else exec). Output capped (~1 MB head) and streamed-then-returned. Auto-detect new matplotlib figures after each call → `savefig()` to the plots dir → return paths. `tryCatch` equivalent (catch `BaseException`, format traceback, still respond). Never-empty: if output overflows, return truncated + tail. On timeout, return a stuck-diagnostic.

**`r-repl` server** (`scripts/r_repl_server.py`): same shape — Python stdio MCP server, session pool, lazy start, proxies to an R worker. The R worker communicates over a **Unix socket** (R's stdin semantics are awkward for a line protocol; a socket is cleaner than duping fd 0/1).

**`repl.R`** (run via `R --no-save --no-restore`, conda-env-pinned): the R namespace holder, patterned on the user's proven `r-cell.sh` wrapper. Per cell: `parse()` → loop `withVisible(eval(ex[[i]], envir=globalenv()))` → print visible values; auto-`ggsave()` on `inherits(r$value,"ggplot")` → return path; `tryCatch` around the whole cell so the response **always** returns (the END-marker insight from r-cell, restated as "the JSON response always returns, even on error"); never-empty/degraded output; on timeout, stuck-diagnostic (`browser()`/`readline()`/`scan()`?). Neutralize interactive-only R functions at setup: e.g. override `dt_table` (DT htmlwidget that opens a browser) → `print(knitr::kable(df))`, re-applied per run as a safety net. Generalize: a setup step that overrides any function that opens a browser/widget/GUI.

**`scripts/_common.py`**: shared between the two servers — output capping, plot-dir management, JSON framing, session-pool logic, restart logic.

## 8. Tool surface

Both servers expose the same shape, scoped per language (`mcp__data-science_python-repl__*` / `mcp__data-science_r-repl__*`). Every tool takes a `session` name (the named-multi-session routing key). Session names are scoped **per server** — a `lmp` session on `python-repl` and a `lmp` session on `r-repl` are independent workers.

| Tool | Signature | Returns | Notes |
|---|---|---|---|
| `run_code` | `(session, code, timeout?)` | `{stdout, stderr, result_repr, plots:[path], error, usage, truncated, degraded}` | Core tool. Lazy-creates the session worker on first call. `result_repr` = last visible value (notebook semantics). `plots` = saved-PNG paths. `error` = traceback/conditionMessage (response still returns). `usage` = wall/cpu/peak_rss. `truncated`/`degraded` flags. |
| `list_variables` | `(session)` | `[{name, type, size, preview, has_children}]` | Positron-style inspector summary, built from the worker namespace. |
| `inspect_variable` | `(session, name, path?)` | nested summary | Drill into a DataFrame's columns / a list's elements by path. |
| `inject` | `(session, path)` | ack | Exec a `kernel.py` (Python) / `kernel.R` (R) sidecar into the namespace — the extensibility hook (§11). |
| `restart` | `(session)` | ack | Kill + respawn the named worker (after crash or to reset state). Namespace wiped. |
| `session_info` | `(session)` | versions, loaded pkgs, wd, var count | Orientation. |

No `view_plot` tool — `run_code` returns plot paths; the agent `Read`s the PNG (the Read tool renders images).

## 9. Worker execution patterns

**Python (`python_worker.py`)** — adapted from wisp-science `kernel_worker.py`:
- JSON-per-line stdin/stdout protocol (duped off fd 0/1 so user subprocesses don't corrupt the stream).
- `_execute_cell`: heuristic — multi-line or statement-leading → exec; single expression → eval + `print(repr(result))`.
- `import_wrapper` monkeypatch: `import pandas` → `_configure_pandas()`; `import matplotlib` → `_neutralize_pyplot_show()`.
- `_CappedStream` / `_StreamingStdout`: ~1 MB cap, truncation marker, never-empty.
- Traceback line-mapped to the user's cell (`<repl:N>` tags via `linecache`).
- Plot capture: after each cell, check for new matplotlib figures (`pyplot.get_fignums()`) → `savefig()` each to the plots dir → return paths; close them so the next call doesn't re-save.

**R (`repl.R`)** — adapted from the user's `r-cell.sh` wrapper (battle-tested across 941 real runs):
- `ex <- parse(text=code); for (i in seq_along(ex)) { r <- withVisible(eval(ex[[i]], envir=globalenv())); if (isTRUE(r$visible)) { if (inherits(r$value,"ggplot")) { ggsave(f, r$value); cat("FIGURE saved:", f) } else print(r$value) } }`.
- `tryCatch({...}, error=function(e) ...)` around the cell → the JSON response always returns (no hangs on error — the marker-protocol insight, restated for JSON).
- `dt_table` override (and a generalize hook) at setup; re-applied per run.
- `options(width=400)` so long lines don't wrap in captured output (r-cell's `-x 400` lesson).
- Output captured via `capture.output`/`evaluate`; never-empty; truncated + tail on overflow.

## 10. Convenience helpers & the base `kernel.py`/`kernel.R`

Each worker pre-loads a small base sidecar at session start (the skill's own helpers):

- **Python (`kernel.py`):** `_peek(obj)` (type-dispatched summary: DataFrame → shape+dtypes+head, list → len+first N, dict → keys+value-types, else repr), `_who()` (variable listing shortcut), `_plot_dir()`, `_fig(n)` (return path of the nth saved figure).
- **R (`kernel.R`):** `who()` (ls with classes), `peek(obj)` (type-dispatched: data.frame → `dim`+`str` head, list → length+`str` of first elements), `fig(n)`.

These are themselves sidecars (definition-only, lazy imports) — loaded via the same `inject` mechanism at session start, so they're a reference example for sidecar authoring.

## 11. Sidecar injection (extensibility)

Other skills extend the namespace without the base skill knowing:

- A skill ships a `kernel.py` (Python) and/or `kernel.R` (R) in its directory: top-level definitions only, all non-stdlib imports inside function bodies, no side-effect code at load (passes an AST gate — the wisp-science convention).
- That skill's `SKILL.md` tells the agent: *"after starting the REPL, call `inject('<path>/kernel.py')` once to load these helpers before using them."*
- The `inject` tool reads the file and execs it into the worker namespace (sent as a protocol message, not a plain `run_code`).
- Example: the EDA skill could ship a `kernel.py` with `profile_column(df, col)`, `quality_report(df)` helpers; its `SKILL.md` instructs the agent to inject them.

This is the adaptation of wisp-science's platform-managed injection (which we can't use) to agent-driven injection.

## 12. Plot handling

- Worker auto-saves figures: Python `matplotlib` → `savefig()` to `${CLAUDE_PLUGIN_DATA}/plots/<session>-<n>.png`; R `ggplot` → `ggsave()`; base R `plot()` → wrap in `png()`/`dev.off()` (a `plot` hook in `repl.R`).
- `run_code` returns plot paths in `plots:[]`.
- The agent `Read`s the PNG to view it (the Read tool renders images).
- The iterate-on-plots behavioral rule (§15) makes this *save-and-look*, not reason-from-the-data-layer.

## 13. Error handling & robustness

- **tryCatch guarantees response (R) / try-except guarantees response (Python):** every cell is wrapped so the JSON response always returns — no hangs on error (r-cell's central robustness lesson).
- **Never-empty / degraded output:** if a cell's output overflows the cap, return truncated + tail with a `truncated: true`/`degraded: true` flag — the agent always sees *something* (r-cell's `_show_output` grace).
- **Worker crash:** `run_code` detects a dead worker → returns a structured "worker died" error → the skill tells the agent to call `restart(session)`. Stdio MCP servers aren't auto-restarted; the *worker* is restartable (the server survives).
- **Stuck code:** `run_code` timeout → return a stuck-diagnostic. In real sessions the observed timeouts were genuinely long code (3.47M-row extracts hitting Claude Code's own 120s Bash timeout), not `browser()`/`readline()` blocks — the latter are prevented upstream by the interactive-function neutralization (§9). The diagnostic covers both: prompt the agent to chunk long code or check for an interactive call.
- **Dependency-ordering errors are expected, not bugs:** `object 'X' not found` after a cell means a dependency hadn't run yet. tryCatch catches it cleanly; the response still returns. The agent runs chunks in dependency order (the `chunks` listing helps; a dependency-aware run-order hint is deferred to v2).
- **Restarts lose state:** restarting a session wipes DB connections and loaded data (`object 'con' not found` after restart in real usage). `restart` is for crashes or deliberate resets — the SKILL.md guidance discourages unnecessary restarts (§15.10).
- **Output too large:** `truncated: true`; the agent paginates via `inspect_variable`.
- **Missing deps:** missing Python/`uv`/`mcp`/R → clear error pointing at `references/setup.md`. `uv run` auto-installs `mcp`.
- **Missing tool-schema misuse:** clear, actionable error messages (r-cell saw 34 `die()`-style misuse errors — better schemas reduce these).

## 14. Configuration

- **Conda env / R path / Python path:** the server reads `INTERACTIVE_REPL_R_ENV` (conda env name, like r-cell's `R_CELL_ENV=nipgen`), `INTERACTIVE_REPL_R_BIN`, `INTERACTIVE_REPL_PY_BIN` env vars (with sensible defaults — `R`/`python3` on PATH). Set per-project via `.claude/settings.json` `env` or the user's shell env.
- **Plot dir:** `${CLAUDE_PLUGIN_DATA}/plots/<session>/`.
- **Output cap:** `INTERACTIVE_REPL_MAX_OUTPUT` (default ~1 MB head; final MCP response summarized to fit the 25k-token default, raisable via `_meta`).
- **Timeout:** `INTERACTIVE_REPL_TIMEOUT` (default 300s, matching r-cell).

## 15. SKILL.md behavioral guidance (the heart of the skill)

The `description` frontmatter triggers on "explore/analyze/iterate on this data in R/Python," "keep a session open," "run this chunk," "what's in this dataframe," even when the skill isn't named.

Body guidance (imperative, for Claude):

1. **The iterate rule.** Once a REPL session is started for a task, keep running code *in it*. Don't re-run a one-shot script to peek at a result — state persists, use it. Re-importing and re-loading each turn wastes tokens and time.
2. **When to start a session.** Start one when you'll iterate: load → transform → inspect → plot → fix assumption. **You don't need to call `start` explicitly** — the first `run_code` auto-creates the named session. Pick a session name matching the task (`lmp`, `infection`, …); keep using it for that task.
3. **When NOT to use the REPL — the agent chooses.** Real sessions show the agent reaching for one-shot `Rscript`/`python` for exploratory SQL+regex text-mining and other one-off extraction (51 one-shot scripts in one session, 0 REPL runs). The REPL's value is **stateful, multi-chunk, state-carrying analysis** — load once, iterate across 50+ chunks sharing DB connections and loaded frames. For one-shot extraction, batch pipelines, or long-running jobs (training, big joins), use one-shot scripts / the `pipeline-maker` skill. Don't force the REPL where a one-shot fits.
4. **Language choice.** Match the surrounding project (pandas vs tidyverse — see the EDA skill's convention). Route to `python-repl` or `r-repl` accordingly.
5. **Save-and-look at plots — but looking is necessary, not sufficient.** When you plot, the worker auto-saves the figure and `run_code` returns the path. **`Read` the PNG to actually see it** — do not reason from the data layer alone. But know that the agent can `Read` a PNG and *still* mis-reason: in a real session it attributed empty histogram panels to "censored markers / white-transparent bars" when the true cause was `count=1` bars on `scale_y_log10()` can't render 1→0 (`log(0)` undefined). Understand the **rendering semantics** (how the geometry renders), not just what the data contains — especially for log/tricky-scale plots. If the user says "the plot looks wrong," believe them first, then look yourself. Do not auto-"fix" a plot because you saw a ggplot/matplotlib warning (`log(0)=-Inf`/`Removed N rows` are normal semantics, not errors) — look at the render first. If `Read` returns "Unsupported Image" (some environments), fall back to verifying key distribution stats numerically.
6. **Absolute paths.** The session's working directory may differ from yours; use absolute paths for `source()`/`read.csv()`/file args (relative paths are unreliable in a driven session).
7. **R conventions.** Prefer `pkg::fun()` over `library()` (the project forbids `library()` — it attaches and clobbers). Prefer `scale_y_sqrt()` over `scale_y_log10()` to avoid the count=1 down-fill artifact.
8. **Multi-session discipline.** One driver per session — don't interleave writes to the same named session from parallel turns. Use distinct names for parallel tasks.
9. **Ad-hoc inspection is first-class.** `run_code` runs any code string; use it freely for quick "what's in this variable" peeks (`_peek(df)`, `dim(df)`, `head(df)`). For notebook/qmd workflows, extract a chunk's code (read the chunk body, or `knitr::purl`) and pass it to `run_code` — a labeled-chunk convenience tool is deferred to v2. The real sessions used ad-hoc inspection nearly as often as named-chunk runs, so don't hesitate to run small peeks in-session.
10. **When to restart (rarely).** After a crash (`run_code` returns "worker died") → `restart(session)`, or to deliberately reset state for a fresh analysis on the same topic. **Do not restart between chunks "to be safe"** — real sessions show restart-cycles lose DB connections and loaded data (`object 'con' not found` after restart). State persistence is the REPL's value; restarting throws it away.
11. **Extensibility hook.** When another active skill ships a `kernel.py`/`kernel.R`, call `inject(path)` once before using its helpers.
12. **Progressive disclosure.** Deep docs live in `references/`: `tools.md` (full tool API), `sidecar-authoring.md` (how to write a `kernel.py` for your skill), `r-setup.md` (conda env, `pkg::fun()` convention, neutralized interactive functions), `troubleshooting.md` (stuck code, missing deps, worker crashes), `plot-iteration.md` (the save-and-look loop, expanded).

## 16. Relationship to other skills

- **`exploratory-data-analysis`:** light touch-up — when the REPL is available, run EDA's steps in-session via `run_code` instead of one-shot scripts. Optionally ship a `kernel.py` with `profile_column`/`quality_report` helpers and `inject` them. The EDA skill's one-shot path remains as a fallback.
- **Bioinformatics skills (`population-genomics`, `pipeline-maker`, …):** opt in via sidecar injection (ship a `kernel.py`/`kernel.R`, instruct the agent to inject). The `bioinformatics` plugin entry ships no `mcpServers`.
- **`pipeline-maker`:** the boundary. The REPL is for *interactive* exploration; `pipeline-maker` is for *reproducible* batch workflows. Don't use the REPL as a pipeline — long batch jobs are one-shot scripts.

## 17. Testing

- **Skill triggering:** copy `data-science/interactive-repl/` to `~/.claude/skills/`, start a fresh Claude Code session, try prompts that should ("explore this CSV in R," "keep a Python session open and iterate") and should not ("build me a Snakemake pipeline") trigger. Iterate on `description`.
- **Servers/workers:** a small `tests/` harness that spawns a worker and asserts: round-trip (`run_code` → stdout), persistent state (a variable set in call 1 is visible in call 2), plot capture (a ggplot/matplotlib figure → saved PNG → readable), crash-restart (kill the worker → `run_code` returns "worker died" → `restart` → works), never-empty (a cell with verbose output returns degraded, not empty), tryCatch-guarantees-response (a cell that errors returns a response, not a hang).
- **Determinism:** per `CLAUDE.md` — scripts are deterministic helpers. The `_common.py` output-capping/protocol-framing is pure and unit-testable.

## 18. Scope: v1 vs deferred

**In v1:** persistent R+Python REPL via two MCP servers; named multi-session; auto-start; sidecar injection; R patterns from r-cell (withVisible/ggsave/tryCatch/never-empty/neutralize); Python patterns from wisp-science; plot-to-disk + Read; the iterate/save-and-look behavioral guidance; conda/env config.

**Deferred to v2+ (YAGNI for v1):**
- Control-plane/data-plane kernel split (the agent is the control plane — no in-kernel orchestration needed).
- `host.llm` fan-out from the kernel (an MCP server can't call back into the agent's LLM).
- `host.view_image` crop boxes (the agent `Read`s the whole PNG; crop is YAGNI).
- Per-cell interrupt (wisp-science's MVP also omits it; long cells block until return).
- Live `stdout_chunk` streaming mid-call (MCP tool calls are request/response, not streaming; we return full stdout at the end).
- `knitr::purl` chunk extraction as a built-in tool (optional convenience helper; can be a `references/` note for qmd/Rmd workflows — the user's `r-split.R` is a reference).
- Multi-session cross-language state sharing.
- A bundled `bin/` CLI fallback.

## 19. Risks & open questions

- **Tool-agnostic departure:** this is the first skill in the repo to ship an MCP server. The departure is deliberate and scoped (only this skill; others remain portable). Flag for a memory update once shipped.
- **R subprocess protocol:** R's stdin is awkward for a line protocol; the spec proposes a Unix socket for R, stdin/stdout JSON-lines for Python. Finalize during implementation planning.
- **Stdio server crash recovery:** stdio MCP servers aren't auto-restarted by Claude Code. The *worker* is restartable (server survives), but if the *server* itself crashes, the agent must re-enable the plugin. Mitigation: keep the server thin (all user code runs in the worker subprocess, so the server rarely crashes).
- **Output token cap:** MCP caps tool output at 25k tokens default (raisable to 500k via `_meta`). The worker caps at ~1 MB and the server summarizes further; large dataframes are paginated via `inspect_variable`.
- **Idle timeout:** 30-min stdio idle timeout may kill a server mid-long-analysis. Configurable via `CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT`; documented in `references/setup.md`.
- **`uv` dependency:** both servers bootstrap via `uv run`. Documented requirement; fallback (plain `python3` + `pip install mcp`) noted in `references/setup.md`.

## 20. File layout

```
data-science/interactive-repl/
├── SKILL.md                      # behavioral guidance (§15), frontmatter triggers
├── references/
│   ├── tools.md                  # full tool API + schemas
│   ├── sidecar-authoring.md      # how to write a kernel.py/kernel.R for your skill
│   ├── r-setup.md                # conda env, pkg::fun(), neutralized fns, scale_y_sqrt
│   ├── troubleshooting.md        # stuck code, missing deps, worker crashes
│   └── plot-iteration.md         # the save-and-look loop, expanded
├── scripts/
│   ├── python_repl_server.py     # MCP stdio server (mcp SDK); session pool; proxies
│   ├── python_worker.py          # namespace holder (≈ wisp-science kernel_worker)
│   ├── r_repl_server.py          # MCP stdio server; session pool; proxies (Unix socket)
│   ├── repl.R                    # R worker (withVisible/ggsave/tryCatch/neutralize)
│   ├── _common.py                # shared: output capping, plot-dir mgmt, JSON framing
│   ├── kernel.py                 # base Python sidecar (peek/who/fig) — ref example
│   └── kernel.R                  # base R sidecar (who/peek/fig)
└── tests/
    └── test_workers.py           # round-trip, persistence, plot, crash-restart, never-empty
```

Marketplace change: add `"./data-science/interactive-repl"` to the `data-science` plugin's `skills` list, and add the inline `mcpServers` block (§5). README: add the skill to the data-science table with a one-line description, and note the new MCP-server convention in the Contributing/Repository-layout section.

---

**Provenance:** patterns adapted from wisp-science's `python/kernel_worker.py` (Python worker), the user's `external/r-cell/r-cell.sh` (R worker patterns, marker/tryCatch robustness, multi-session, plot-to-disk — validated across 941 real runs), and Positron's inspector/data-explorer concepts (variable summary). These are credited here for design traceability; the shipped `SKILL.md` and scripts are original and self-contained, and do not reference openclaw-science or any external plugin.
