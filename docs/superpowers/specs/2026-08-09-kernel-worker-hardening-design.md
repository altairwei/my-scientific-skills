# Kernel-worker hardening (interrupt / attribution / caps / hygiene)

Date: 2026-08-09
Status: design (user-approved 2026-08-09)

## 1. Background — the reference implementation

The user pointed at `external/science-skills/kernel_worker.py` — the
production kernel worker of the Claude Science (Operon) stack. Our
`python_worker.py` is already an earlier adaptation of this same file
("Adapted from wisp-science's kernel_worker.py"), so the architecture is
shared: JSON-per-line stdio protocol with id matching, always-respond
error contract, eval/exec + repr printing, pandas display config on import,
per-cell linecache tags. The evolved reference adds a hardening layer we
never got. Diff against our worker:

**What we already have** (no action): fd dup-off protocol channel,
eval/exec + repr, pandas display config, lazy-install with version-keyed
py-site, per-cell compile tags, output cap with visible marker (post-hoc).

**What the reference adds and we lack** (this spec):

| Gap | Severity | Our current failure mode |
|---|---|---|
| No SIGINT discipline / interrupt | P1 | stuck cell blocks the server call forever; only `restart` (state wipe) recovers |
| `os.set_inheritable` on protocol fds | P0 | user daemon inheriting the protocol pipe write-end prevents server EOF → "worker died" detection hangs |
| Write-time capped output buffer | P0 | runaway print loop grows StringIO unboundedly → OOM before the post-hoc cap runs |
| Error attribution (lineno + failing expression) | P1 | agent gets a full traceback, no precise failing sub-expression |
| Per-cell usage metrics | P2 | no wall/cpu/RSS visibility (matters on HPC) |
| `exit()`/`quit()` shadowing | P2 | bare SystemExit traceback (survives by accident via `except BaseException`) |
| linecache eviction | P2 | unbounded growth over long sessions |
| Secret-var stripping | P2 | user code (or prompt-injected code) can read API keys from the worker env |

**Explicitly NOT ported** (threat model mismatch): dlopen audit hook,
protocol fd identity/recovery sabotage hardening, BYOC token scrub,
origin-gated figure capture, live stdout streaming. Operon hardens against
users typing hostile code into a shared kernel; our model is a personal
REPL where only the agent runs code — the residual risk is prompt injection.
Live streaming (`stdout_chunk` frames) is a protocol change deferred to a
separate evaluation; the fd-0 stdin wedge in the R worker is likewise
deferred.

## 2. Empirical validation (probes, 2026-08-09)

All claims below were validated with probe scripts driving real workers over
stdio (both workers launched exactly as the server launches them).

| Probe | Result |
|---|---|
| R SIGINT during a running cell (current) | worker dies rc=1 ("停止执行"); interrupt condition escapes the `error=` arm and aborts the script — full state loss |
| R SIGINT while idle (current) | worker dies the same way |
| R SIGINT during a cell (patched: `tryCatch(interrupt=)` arm) | response with `interrupted=TRUE`, loop survives, sink state clean, subsequent cells fine |
| R SIGINT while idle (patched) | **still dies** — R does not surface a catchable interrupt condition from a blocked `readLines` on a connection; mitigated by the server-side busy guard (the server NEVER signals an idle worker) |
| R `conditionCall` attribution | nested `stop()` inside `f()` → `deparse(conditionCall(e))` = `"f()"`; genuine argument error `sd(v, w=1)` → `"sd(v, w = 1)"` (full expression, non-NULL). (Note: `mean(v, w=1)` does NOT error — its `...` reaches primitive `sum`, which silently drops unknown named args; `d$zzz` on a data.frame partial-matches to NULL. Probe design artifacts, not attribution gaps.) |
| Python SIGINT during a cell (current) | worker survives via `except BaseException`; response has no `interrupted` flag — agent cannot distinguish interrupt from error |
| Python SIGINT while idle (current) | worker neither dies nor responds — zombie state (signal lands in `readline`, corrupts the main loop) |
| Python SIGINT during a cell (patched: conditional handler) | response `interrupted=true` with KeyboardInterrupt traceback; loop survives; next call fine |
| Python SIGINT while idle (patched) | handler swallows the signal; loop continues; next call fine |
| Python user-raised `raise KeyboardInterrupt` (patched) | `interrupted=false` — the delivered-SIGINT marker distinguishes it (per reference semantics) |

## 3. Protocol extension (both workers)

The response object gains three keys (server maps them into the MCP result):

```json
{
  "id": "...", "stdout": "...", "stderr": "...", "error": null,
  "plots": [...], "truncated": false, "degraded": false,
  "interrupted": true,
  "trace": {"error_lineno": 3, "error_call": "sd(v, w = 1)"},
  "usage": {"wall_s": 0.42, "cpu_s": 0.12, "peak_rss_kb": 82432}
}
```

- `interrupted` — bool; only true when a SIGINT was actually DELIVERED
  during the cell (a user `raise KeyboardInterrupt` / `stop()` is an
  ordinary error).
- `trace` — Python: `error_lineno` (deepest frame whose `co_filename` is
  the cell tag) + `error_call` (PEP 657 byte-col slice of the failing
  sub-expression, ≤200 chars). R: `error_call` only (`deparse(conditionCall(e))`,
  omitted when NULL). Both failure-safe (return None/omit on any hostile
  exception object).
- `usage` — `wall_s` (perf_counter / `proc.time()`), `cpu_s` (user+sys,
  self + reaped children), `peak_rss_kb` (VmHWM from
  `/proc/self/status`; getrusage fallback on non-Linux).

## 4. Python worker changes (`scripts/python_worker.py`)

1. **Conditional SIGINT handler** (ported, simplified from the reference):
   a `_in_user_code` bracket flag set around `_execute_cell`; the handler
   raises a marker-carrying `KeyboardInterrupt` (`ki._repl_delivered = True`)
   only inside the bracket and is one-shot (self-clears); everywhere else
   the signal is swallowed, so idle readline / json handling / response
   write can never be killed. The response's `interrupted` = presence of
   the marker on the caught exception.
2. **`_CappedStringIO`** for stdout and stderr capture: write-time cap of
   `MAX_OUTPUT - 256` UTF-8 bytes with headroom for the marker; `getvalue()`
   appends `\n…(buffer capped at N KB; M further bytes dropped)\n` reporting
   the REAL dropped byte count; truncation honors UTF-8 boundaries (encode →
   slice bytes → decode); write() honours the `io` contract (returns code
   points written-or-consumed). Replaces the unbounded `io.StringIO()`;
   `_common.cap_output` stays as a server-side safety net. `truncated` is
   derived from the capped object's dropped counter.
3. **`os.set_inheritable(protocol_in.fileno(), False)`** and the same for
   `protocol_out` — user subprocesses can no longer inherit the protocol
   pipe write-end (server EOF detection) or read-end.
4. **Quitter shadow**: namespace + `builtins` `exit`/`quit` replaced by a
   callable that raises a marker subclass of `SystemExit` without touching
   stdin; the caught response appends "(exit()/quit() is disabled here —
   close the session with the `close(session)` tool)". The marker gates the
   hint (a library `sys.exit()` is not blamed on REPL muscle memory).
5. **linecache eviction**: `_lc.cache.pop(f"<repl:{counter - 128}>", None)`
   after registering the cell (counter-keyed, like the reference).
6. **Secret stripping**: at startup, pop the static list
   `ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, OPENAI_API_KEY,
   OPENROUTER_API_KEY, GITHUB_TOKEN, HF_TOKEN, AWS_ACCESS_KEY_ID,
   AWS_SECRET_ACCESS_KEY` from `os.environ` (worker process only; the server
   env is untouched). Never strip vars the worker needs
   (`CLAUDE_PLUGIN_DATA`, `INTERACTIVE_REPL_*`, `PATH`, conda env vars,
   `SLURM_*`).
7. **usage**: `time.perf_counter()` delta; `resource.getrusage(RUSAGE_SELF |
   RUSAGE_CHILDREN)` user+sys delta; peak RSS via `/proc/self/status`
   VmHWM, getrusage fallback (macOS ru_maxrss is bytes → /1024).
8. **error attribution**: `_error_lineno(exc, cell_tag)` — deepest
   `co_filename == cell_tag` frame; `_error_call(exc, cell_tag, code)` —
   PEP 657 `co_positions()` from `tb_lasti // 2`, byte-col slice of the
   encoded source line (non-ASCII-safe), ≤200 chars, None on any failure.
   Both wrapped so hostile exception objects (raising descriptors on
   `__traceback__` etc.) classify as None, never escape.

No protocol write lock is added: we do not stream, and all writes to the
protocol fd happen on the main thread after cell completion (user threads
can only reach the captured StringIO, not the protocol fd). If live
streaming is adopted later, add the reference's `_PROTOCOL_WRITE_LOCK`.

## 5. R worker changes (`scripts/repl.R`)

1. **Interrupt arm**: `tryCatch({...}, interrupt = function(e) { interrupted <<- TRUE; NULL }, error = function(e) conditionMessage(e))` in
   `run_cell`; response carries `interrupted` and `error = "interrupted"`.
   Validated: loop survives, sink/textConnection state clean, subsequent
   cells work.
2. **readLines guard**: `tryCatch(readLines(.repl$con_in, n=1), interrupt = function(e) "", ...)` — an idle signal becomes a skipped empty line
   instead of EOF/abort. (Note: probes show R still dies on a signal
   delivered while blocked in readLines — this arm is belt-and-suspenders;
   the operative protection is the server busy guard.)
3. **Response-write guard**: `tryCatch(.repl$write_json(res), interrupt = function(e) NULL)` — a signal in the write window cannot kill the loop
   (the response may be lost; the server's read timeout covers that).
4. **error_call**: `deparse(conditionCall(e))` captured in the error
   handler, omitted from the response when NULL.
5. **usage**: `proc.time()` elapsed (user+sys, delta across the cell);
   peak RSS by parsing `readLines("/proc/self/status")` VmHWM, NA fallback
   on non-Linux.
6. **Secret stripping**: `Sys.unsetenv()` for the same static list at
   startup.
7. **Unknown-name request fields**: keep `interrupted`/`trace`/`usage`
   absent-or-null in the base responses (invalid-JSON path, run_loop error
   path) — the server defaults them.

## 6. Server changes (`scripts/repl_server.py`)

1. **New tool `interrupt(session)`** — cancel the running cell and keep the
   worker alive:
   - local mode: `os.kill(session.proc.pid, signal.SIGINT)` directly to
     the worker process;
   - slurm mode: `subprocess.run(["scancel", "--signal=INT", job_id], ...)`
     (salloc/srun local signal forwarding is unreliable; the job_id came
     from the ready handshake);
   - busy guard: if the session has no in-flight request → structured
     error "no cell running" (never signal an idle worker — R cannot
     survive it, per probes).
   Returns `{ok, interrupted: bool}`; a `worker died` response if the
   process is already gone.
2. **`run_code` timeout becomes real**: `_recv` gains a selectors-based
   deadline. On timeout the server auto-interrupts once, then waits a
   10 s grace for the response; if still nothing, returns
   "cell unresponsive — call `restart(session)`" WITHOUT killing the
   worker (it may be in uninterruptible C code). The tool docstring
   changes from "advisory in v1".
3. **Per-session busy lock**: a `threading.Lock` per `_Session`, acquired
   non-blockingly around the request/response exchange; a concurrent
   `run_code`/`run_chunk` on a busy session returns a structured error
   "session busy running a cell — wait or call `interrupt(session)`"
   (today two concurrent calls would interleave on the pipe).
4. **`RunResult` gains `interrupted: bool`, `trace: {error_lineno,
   error_call} | null`, `usage: {wall_s, cpu_s, peak_rss_kb} | null`**
   (defaults false/None); `session_info` unchanged.

## 7. Docs changes

- `SKILL.md` — tools list gains `interrupt(session)`; the "stuck cell"
  guidance becomes: call `interrupt` first, read the partial output, and
  only `restart` if the worker is unresponsive (restart stays the
  last resort — it wipes state); run_code line mentions the real timeout
  semantics.
- `references/tools.md` — full `interrupt` API section.
- `references/troubleshooting.md` — "stuck cell" section rewritten around
  interrupt-first; `exit()`/`quit()` note; output-cap note.
- `references/slurm-hpc.md` — interrupt via `scancel --signal=INT` in the
  Semantics section.
- `references/r-setup.md` — nothing new required (no new env vars).

## 8. Tests

- `tests/test_python_worker.py` — CappedStringIO unit tests (cap at
  byte boundary, UTF-8 boundary trim, real dropped-count marker, write()
  contract); quitter (`exit()` → error, worker survives); secret
  stripping (set a secret var, `os.environ` lookup returns None in the
  cell); usage fields present; `interrupted` false for normal errors;
  error_call PEP 657 slice (e.g. `d["missing"]` on a dict → the failing
  sub-expression); linecache eviction (internal — assert cache size
  bounded).
- `tests/test_r_worker.py` — interrupt during `Sys.sleep` → `interrupted`
  true, loop survives, next call works; error_call shape for a nested
  `stop()`; usage fields present.
- `tests/test_python_server.py` — `interrupt(session)` end-to-end:
  infinite loop cell, interrupt, `interrupted` in result, namespace
  survives, next `run_code` works; idle-session interrupt rejected;
  busy-session rejection (concurrent call); timeout→auto-interrupt path.
- `tests/test_slurm.py` — slurm interrupt records `scancel --signal=INT
  4242` in the fake-scancel log; worker stays alive after interrupt.
- `tests/test_smoke.py` — unchanged (regression).

## 9. Out of scope (deferred)

- Live stdout streaming (`stdout_chunk` frames + protocol write lock) —
  separate evaluation.
- R-side fd-0 stdin wedge (`system()` children inheriting the protocol
  read end) — separate evaluation (needs R dup/CLOEXEC probing).
- dlopen audit hook, protocol fd identity/recovery hardening, BYOC token
  scrub — operon threat model, not ours.
