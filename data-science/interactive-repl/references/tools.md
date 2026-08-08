# Tools — interactive-repl

The `repl` server exposes nine tools (`run_code`, `run_chunk`, `list_variables`,
`inspect_variable`, `inject`, `restart`, `close`, `session_info`, `worker_mode`) under the
`mcp__<plugin>_repl__<tool>` namespace. Every tool takes a `session` name first —
the language comes from the name's prefix (`r:` / `py:`), and sessions are
auto-created on first `run_code`. Prefixed sessions are independent: `r:lmp` and
`py:lmp` are unrelated workers.

## run_code(session, code, timeout=300) → RunResult

Execute code in the named persistent session. Variables, imports, and loaded data
persist across calls.

```jsonc
{
  "stdout": "2\n",
  "stderr": "",
  "error": null,                 // traceback / conditionMessage, or null on success
  "plots": ["/path/to/fig-1-...png"],
  "truncated": false,            // true if stdout exceeded the cap
  "degraded": false              // true if stdout was empty and stderr was surfaced
}
```

- `error` is `null` on success; the response **always** returns (errors are caught —
  `tryCatch` in R, `try/except` in Python — so a bad cell never hangs the session).
- `plots` lists PNGs auto-saved by the worker (matplotlib figures / ggplot objects).
  `Read` a path to view it. Figures are closed after save.
- The `timeout` parameter is advisory in v1 — the worker blocks until the code returns;
  a stuck cell surfaces as a `worker died` error (call `restart`).

## list_variables(session) → VarList

```jsonc
{ "variables": [ { "name": "df", "type": "DataFrame", "size": "100 x 5",
                   "preview": "...", "has_children": true } ] }
```

Lists non-underscore session variables with a type-dispatched summary.

## inspect_variable(session, name, path?) → InspectResult

```jsonc
{ "name": "df", "repr": "...", "error": null }
```

Drill into a variable by path: `inspect_variable("df", ["colname"])` (Python) or
`inspect_variable("lst", [0])`. Returns the object's `str`/`repr`/`head`.

## inject(session, path) → Ack

```jsonc
{ "ok": true, "message": "injected /path/to/kernel.py" }
```

Exec a `kernel.py` (Python) / `kernel.R` (R) sidecar into the session namespace. Call
once per sidecar per session, before using its helpers. See `sidecar-authoring.md`.

## restart(session) → Ack

Kill + respawn the named worker — wipes the namespace. Use after a `worker died`
error or to deliberately reset. **Loses DB connections and loaded data** — use sparingly.

## close(session) → Ack

```jsonc
{ "ok": true, "message": "closed session 'r:lmp'" }
```

Kill the named session's worker and release it — closes the transport, terminates the
process, and (slurm mode) scancels the allocation. Unlike `restart`, the worker is NOT
respawned; the next `run_code` on this name starts a fresh, empty session. Never creates
a session: closing a name that isn't running is a no-op success
(`{ "ok": true, "message": "no running session 'r:ghost'" }`). Sessions are not
auto-closed — call `close` when the task is done.

## session_info(session) → SessionInfo

```jsonc
{ "session": "r:lmp", "running": true, "pid": 12345, "plot_dir": "/.../plots" }
```
