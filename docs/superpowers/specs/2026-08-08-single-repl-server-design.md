# Single `repl` server — consolidate the two MCP servers

Date: 2026-08-08
Status: design (user-approved, sections 1–5)

## 1. Background: why two servers existed

The original design (`2026-08-05-interactive-repl-design.md`) shipped one MCP
server per language, `python-repl` and `r-repl`, with a four-part rationale:

1. **Language boundary = process boundary.** The engine is the language-runtime
   worker (`python_worker.py` with an exec/eval namespace heuristic vs
   `repl.R` run via `R --no-save`); the MCP server is thin Python glue that
   proxies to it. Different runtimes, transports, and interactive-function
   neutralization hacks made the language boundary look like the natural seam.
2. **Tool namespace as routing.** `mcp__data-science_python-repl__*` vs
   `mcp__data-science_r-repl__*` — the agent routes by tool name, zero dispatch.
3. **Independent lifecycle & config.** R may be absent from PATH on HPC login
   nodes (conda-env pinned via `INTERACTIVE_REPL_R_ENV`/`R_BIN`); python-repl
   must keep working regardless.
4. **Crash isolation ×2.** Worker subprocess isolation (worker dies → server
   survives and restarts it) plus server-level isolation.

## 2. The observation that breaks the premise

Measured against the current code (`HEAD a444a6e`):

- **The glue is ~64% identical.** After name normalization
  (`python_repl_server` ↔ `r_repl_server`), the two scripts differ in only 287
  of 805 lines, and the differing 36% is almost entirely the irreducible
  language core: worker launch command, transport (stdio JSON-lines vs TCP
  localhost socket — R's `socketConnection` is TCP-only), the injected
  list-variables code, the base sidecar (`kernel.py` vs `kernel.R`), and R's
  conda env config. Session pool, `_call_worker`, all 8 tools (including the
  full `run_chunk` notebook-routing loop), `_slurm.py` wiring, `worker_mode`,
  output capping, degraded flags — all duplicated inline.
- **`_common.py` holds only the pure helpers** (51 lines: cap/never-empty/
  plot-dir/JSON framing); the shared logic was never extracted, it was copied.
- **Same-project bilingual use is rare.** The "both servers live, independent"
  justification pays off only for projects mixing R and Python, which is the
  uncommon case.
- **Zero external references.** No file outside `interactive-repl/` mentions
  either server name (verified by repo-wide grep: only SKILL.md, references/,
  tests/, scripts/ are internal). Migration cost is fully contained.
- **The glue duplication was paid twice this week** — `worker_mode`, the slurm
  fields in `session_info`, and `_slurm.py` wiring landed in both servers.

## 3. Positioning

**One `repl` MCP server = session manager.** Language is an attribute of a
*session* (the worker process), not of the MCP layer. The MCP layer manages
session lifecycle — session pool, lazy create, proxy, output capping,
`worker_mode`/slurm — and language lives in the worker, bound via the session
name. This is the Jupyter kernel-host model: one host, one process per
language kernel.

## 4. API

- **Marketplace:** `python-repl` + `r-repl` → one `repl` entry. Tools become
  `mcp__data-science_repl__*` — 8 tools, not 16.
- **Session names carry the language:** `r:<task>` / `py:<task>`. Lazy
  auto-create is preserved (first `run_code` on `r:lmp` spawns the R worker).
- **Unprefixed or unknown-prefix names → structured error** (error-dict
  pattern, never a raised exception): `"ambiguous session name — use r:<name>
  or py:<name>"`.
- **All tool signatures unchanged** — the `session` parameter upgrades from
  routing key to language+routing key. `run_code`, `list_variables`,
  `inspect_variable`, `inject`, `restart`, `session_info`, `worker_mode`,
  `run_chunk` all keep their call shapes.
- **`run_chunk` behavior-preserving:** chunks are filtered by the session's
  language; foreign-language chunks are listed in `skipped` (exactly what the
  two per-server `run_chunk`s do today). Mixed-language notebooks → one call
  per language session (`r:xxx` for R chunks, `py:xxx` for Python chunks).
- **`worker_mode` / `session_info` / slurm wiring exist once.**
- **Breaking change, once, no compat aliases** — justified by zero external
  references.

## 5. Implementation

New `scripts/repl_server.py` (~500 lines) replaces both servers. The core is a
language registry — the 36% language-specific core, keyed by prefix:

```python
_LANGUAGES = {
    "py": {
        "worker_cmd": lambda: [sys.executable, HERE / "python_worker.py"],
        "transport": "stdio",            # JSON lines
        "list_vars_code": _PY_LIST_VARS, # globals() inspection
        "sidecar": "kernel.py",
    },
    "r": {
        "worker_cmd": _r_launch_cmd,     # conda run wrapper + R --no-save repl.R
                                         #   (INTERACTIVE_REPL_R_ENV/R_BIN logic moves as-is)
        "transport": "tcp",              # localhost socket (R socketConnection is TCP-only)
        "list_vars_code": _R_LIST_VARS,  # ls()/str() inspection
        "sidecar": "kernel.R",
    },
}
```

- `_parse_session(name) -> (lang, bare)`; session pool keyed by the full
  prefixed name (`r:lmp` and `py:lmp` are distinct sessions).
- The module-level `_LANG` constant is replaced by per-session lang; the
  `run_chunk` filter becomes `c.language != lang`.
- **Untouched:** `python_worker.py`, `repl.R`, `kernel.py`/`kernel.R`,
  `discover.py`, `setup.sh`, `_slurm.py` — all language-side or server-agnostic
  work from the last two weeks stays as-is. Transport duality (stdio vs TCP) is
  preserved; unifying it would mean rewriting `repl.R`'s protocol for a
  platform limitation, not worth it.
- `_common.py` stays as pure helpers; no further extraction — consolidation
  *is* the dedup.
- Tool docstrings become generic ("…in a persistent REPL session — `r:<name>`
  for R, `py:<name>` for Python"), since one tool now serves both languages.

## 6. Migration

- Delete `scripts/python_repl_server.py` and `scripts/r_repl_server.py`; add
  `scripts/repl_server.py`; marketplace.json `data-science` entry gets one
  `repl` mcpServer.
- **Tests:** `tests/test_python_server.py` and `tests/test_r_server.py` keep
  their file structure and point at the merged server with prefixed session
  names (`s1` → `py:s1` / `r:s1`); `test_slurm.py` server-level cases and
  `test_smoke.py` likewise. New tests: prefix parsing (valid / ambiguous /
  unknown prefix) and cross-language isolation (`r:lmp` vs `py:lmp`
  independent namespaces).
- **Docs sweep** (verified mention counts): `SKILL.md` (7), `README.md` (3),
  `references/notebook-iteration.md` (4), `references/r-setup.md` (3),
  `references/tools.md` (2), `references/troubleshooting.md` (1).
  `references/slurm-hpc.md` (0 — generic wording, verify anyway). SKILL.md
  gains a short session-naming convention paragraph (`r:<task>` / `py:<task>`,
  and what the ambiguity error means).

## 7. Trade-offs

| Decision | Cost / rationale |
|---|---|
| Shared session namespace | `r:lmp` vs `py:lmp` are distinct sessions — the "rarely bilingual" assumption; mixed notebooks isolate via two session names |
| Generic tool docstrings | Agent routes by session prefix instead of tool names — SKILL.md teaches it, ambiguity errors catch mistakes |
| No compat aliases | Zero external references; one-time rename avoids permanent double wiring |
| Tool surface stays 8 | No opportunistic feature changes — this round is architecture only |
| Transport duality kept | R-side platform constraint; not worth rewriting repl.R |

## 8. Out of scope

- Tool-surface changes (keep the 8 tools as-is)
- Worker or transport unification (Python stdio ↔ R TCP)
- Compat aliases or dual-naming periods
