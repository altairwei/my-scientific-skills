# Project-Scoped Config + Stdio-Only Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (1) Replace the user-level `~/.bashrc` config flow with a project-scoped one (agent asks the user, writes `.claude/settings.local.json`, new `INTERACTIVE_REPL_PY_BIN`, version-keyed `py-site`); (2) remove TCP/token/tunnel transport entirely — all workers speak stdio, slurm launches via `salloc <flags> srun <flags> <worker>`.

**Architecture:** Workers become pure stdio (python keeps its fd-dup; R moves off `socketConnection` onto `readLines(file("stdin"))` + `cat(file="")` with `--quiet --no-echo`, warnings captured via `withCallingHandlers`). The server gets ONE launch path (Popen pipes + tolerant ready-read with deadline) and a tolerant id-matching `_recv` (skips non-JSON lines — R child-process output). `_slurm.launch` builds the salloc/srun argv; token, ports, tunnels, and the `transport` fields are deleted.

**Tech Stack:** Python MCP server (`repl_server.py`), `python_worker.py`, `repl.R`, `_slurm.py`; pytest + pytest-asyncio in-process client; fake srun/scancel/salloc shims; real R 4.3.3 for worker tests.

**Spec:** `docs/superpowers/specs/2026-08-09-project-config-and-stdio-transport-design.md` (user-approved). R stdio feasibility was verified empirically 2026-08-09 (readLines/stdin, cat/stdout outside sink windows, withCallingHandlers warnings, `--no-echo` kills the `-f` source echo; `sink(type="message")` is broken — do NOT use it).

**Test command** (run from `data-science/interactive-repl/`):

```bash
uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/ -q
```

---

### Task 1: stdio-only transport (workers + server + slurm, one commit)

**Files:**
- Modify: `data-science/interactive-repl/scripts/repl.R` (stdio protocol rewrite)
- Modify: `data-science/interactive-repl/scripts/python_worker.py` (delete TCP branches + token)
- Modify: `data-science/interactive-repl/scripts/_slurm.py` (launch via salloc chain; delete tunnel machinery)
- Modify: `data-science/interactive-repl/scripts/repl_server.py` (unified `_start`, tolerant `_recv`, surface deletions)
- Modify: `data-science/interactive-repl/tests/test_r_worker.py`, `test_python_worker.py`, `test_r_server.py`, `test_slurm.py`

> Task 1's steps are one coupled unit (a worker change breaks server tests until the server is converted). The suite is green only at Step 7 — intermediate steps may be red. Do not stop on red mid-task; the TDD beats below are worker-level.

- [ ] **Step 1: Write the new tests + delete the obsolete ones (red phase)**

**test_r_worker.py — replace the socket-based harness with a stdio one (full file):**

```python
import json, os, subprocess, pathlib

HERE = pathlib.Path(__file__).parent
REPL_R = HERE.parent / "scripts" / "repl.R"


def _spawn():
    proc = subprocess.Popen(
        ["R", "--quiet", "--no-echo", "--no-save", "--no-restore", "-f", str(REPL_R)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    ready = json.loads(proc.stdout.readline())
    assert ready.get("ready") is True, f"bad ready marker: {ready}"
    return proc


def _call(p, code, rid="t"):
    p.stdin.write(json.dumps({"id": rid, "code": code}) + "\n")
    p.stdin.flush()
    line = p.stdout.readline()
    while line:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            line = p.stdout.readline()
            continue
        if obj.get("id") == rid:
            return obj
        line = p.stdout.readline()
    raise AssertionError("EOF before response")


def test_r_roundtrip():
    p = _spawn()
    try:
        r = _call(p, "1 + 1")
        assert r["error"] is None
        assert "2" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_r_persistence():
    p = _spawn()
    try:
        _call(p, "x <- 42")
        r = _call(p, "x * 2")
        assert "84" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_r_error_returns_response():
    p = _spawn()
    try:
        r = _call(p, "stop('boom')")
        assert r["error"] is not None and "boom" in r["error"]
        # session still usable after an error
        r2 = _call(p, "1 + 1")
        assert r2["error"] is None and "2" in r2["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_r_warning_captured_in_stderr_field():
    """Warnings are muffled (execution continues) and surface in stderr."""
    p = _spawn()
    try:
        r = _call(p, 'warning("careful"); 42')
        assert r["error"] is None
        assert "careful" in r["stderr"]
        assert "42" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_r_ggplot_saved_to_png(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    p = _spawn()
    try:
        # last expression is the ggplot (visible) → withVisible → ggsave
        r = _call(p, "library(ggplot2); "
                        "ggplot(data.frame(x=1:3, y=c(1,4,9)), aes(x,y)) + geom_point() + geom_line()")
        assert r["error"] is None
        assert len(r["plots"]) >= 1
        assert os.path.exists(r["plots"][0])
    finally:
        p.stdin.close(); p.terminate()


def test_dt_table_overridden_to_kable():
    p = _spawn()
    try:
        r = _call(p, "dt_table(data.frame(a=1:3, b=c('x','y','z')))")
        assert r["error"] is None
        assert "|" in r["stdout"]  # kable prints a markdown-style table
    finally:
        p.stdin.close(); p.terminate()
```

**test_r_server.py — append the tolerant-reader regression test:**

```python
@pytest.mark.asyncio
async def test_r_child_output_tolerated(monkeypatch, tmp_path):
    """R system() output leaks raw lines onto the protocol stream — the
    tolerant reader skips non-JSON lines and returns the matching response."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "r:noise1", "code": 'system("echo RAW-NOISE"); 1 + 1'})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]
```

**test_python_worker.py — delete `test_worker_tcp_mode_ready_and_roundtrip` (lines 175-212) and drop the now-unused `import socket` (line 1).**

**test_slurm.py — add the fake salloc shim and update `_install_shims`:**

Add after `FAKE_SCANCEL`:

```python
FAKE_SALLOC = textwrap.dedent("""\
    #!/bin/sh
    echo "salloc $*" >> "$FAKE_SALLOC_LOG"
    # Strip flags (same heuristic as FAKE_SRUN) until the command — here
    # `srun` — then exec it; the srun shim sets SLURM_* and execs the worker.
    while [ $# -gt 0 ]; do
      case "$1" in
        */*) break ;;
        R|conda|srun) break ;;
        *) shift ;;
      esac
    done
    exec "$@"
    """)
```

Change `_install_shims` default: `def _install_shims(tmp_path, monkeypatch, names=("srun", "scancel", "salloc")):` — the body writes `FAKE_SRUN` for `srun` else `FAKE_SCANCEL`; make it select per name:

```python
def _install_shims(tmp_path, monkeypatch, names=("srun", "scancel", "salloc")):
    """Write fake srun/scancel/salloc shims to tmp_path, put them on PATH, and
    point their log env vars at log files. srun records argv, injects SLURM_*
    env, and execs the real worker command; salloc records argv and execs
    srun; scancel records its args."""
    for name in names:
        body = {"srun": FAKE_SRUN, "scancel": FAKE_SCANCEL, "salloc": FAKE_SALLOC}[name]
        shim = tmp_path / name
        shim.write_text(body)
        shim.chmod(0o755)
        monkeypatch.setenv(f"FAKE_{name.upper()}_LOG", str(tmp_path / f"{name}.log"))
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
```

**test_slurm.py — delete (whole tests):**
- `test_new_token_is_32_hex_chars` (lines 21-22)
- `test_login_host_env_override` (25-27) and `test_login_host_defaults_to_gethostname` (30-32)
- `test_tunnel_cmd_argv` (44-51)
- `test_transport_default_and_override` (89-97)
- `test_slurm_python_token_mismatch_rejected` (223-246)
- `FAKE_SSH` (286-335), `test_tunnel_python_end_to_end` (338-359), `test_tunnel_r_end_to_end` (362-380)
- unused imports: `import re` (line 2) and `import socket` (line 3)

**test_slurm.py — update the surviving tests:**

`test_slurm_python_end_to_end`: delete `assert si["transport"] == "direct"` (line 179); after the `srun.log` assertion add:

```python
        assert "--partition=test -c 4" in (tmp_path / "salloc.log").read_text()
```

`test_slurm_r_end_to_end`: delete `assert si["transport"] == "direct"` (line 265).

`test_worker_mode_probe_defaults`: delete `assert sc["transport"] == "direct"` (line 395) and `monkeypatch.delenv("INTERACTIVE_REPL_TRANSPORT", ...)` (line 387); change line 396 to:

```python
        assert set(sc["probe"]) == {"srun_available", "already_in_allocation"}
```

`test_worker_mode_switch_routes_new_sessions`: delete `monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")` (line 402).

`test_worker_mode_local_overrides_env`: delete `assert si["transport"] == "local"` (line 432).

`test_worker_mode_switch_does_not_affect_existing_sessions`: delete `monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")` (line 439) and `assert si["transport"] == "direct"      # launched under slurm, still slurm` (line 451).

`test_worker_mode_r_server_smoke`: change line 463 to:

```python
        assert set(sc["probe"]) == {"srun_available", "already_in_allocation"}
```

- [ ] **Step 2: Run the new worker-level tests — they FAIL (old repl.R requires REPL_PORT)**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_r_worker.py -v`
Expected: fail — R exits with "REPL_PORT env var must be set" (or the ready read hangs/EOF).

- [ ] **Step 3: Rewrite `scripts/repl.R` (full file)**

```r
#!/usr/bin/env Rscript
# data-science/interactive-repl/scripts/repl.R
# Persistent R namespace over a JSON-per-line stdio protocol.
#
# Requests arrive on stdin (readLines(.repl$con_in, n=1) — blocks on the pipe,
# EOF → character(0) → exit); responses go to stdout via cat(file="") +
# flush(stdout()). The per-cell sink(type="output") window never overlaps
# protocol writes, so responses cannot be captured. Warnings are collected
# with withCallingHandlers (muffled, execution continues) and surface in the
# response's stderr field; R's message sink is NOT usable here — it also
# captures stderr() writes and dies silently (verified 2026-08-09). User
# system()/child-process output leaks raw lines onto stdout — the server's
# tolerant reader skips non-JSON lines.
#
# PROTOCOL STATE LIVES IN A PROTECTED .repl ENV (dot-prefixed → hidden from ls(),
# and out of the bare-name slot so user code can't clobber it). User code evals
# in globalenv() — clean. Neutralized helpers (dt_table → kable) are ATTACHED on
# the search path as a FALLBACK: the user's own dt_table wins; rm("dt_table")
# removes the user's and falls back to the worker version. ls(.GlobalEnv)
# lists user objects only.
#
# Env: none required — SLURM_JOB_ID / SLURM_JOB_NODELIST (set by srun) are read
# for the ready marker so session_info can report the job.
# Eval logic adapted from external/r-cell/r-cell.sh's _build_wrapper (withVisible
# + eval in globalenv, ggsave on ggplot, tryCatch guarantees the response always
# returns). Neutralizes interactive R functions that block/error headless.

.repl <- new.env(parent = emptyenv())
.repl$con_in <- file("stdin", "r")
options(width = 400)  # wide so captured R lines don't wrap in the response

.repl$plot_dir <- function() {
  d <- file.path(Sys.getenv("CLAUDE_PLUGIN_DATA", "/tmp/interactive-repl-data"), "plots")
  dir.create(d, recursive = TRUE, showWarnings = FALSE)
  d
}

# plots is wrapped in as.list() on the way out so a length-1 character vector
# serializes as a JSON array ["..."], not a scalar "..." — the server's
# RunResult.plots is list[str], and a scalar string fails pydantic validation.
.repl$write_json <- function(obj) {
  cat(jsonlite::toJSON(obj, auto_unbox = TRUE, null = "null"), "\n", sep = "", file = "")
  flush(stdout())
}

.repl$dt_table_impl <- function(df, digits = NULL, caption = NULL, ...) {
  if (!is.null(caption)) cat("## ", caption, "\n", sep = "")
  print(knitr::kable(df))
}

# Attach the neutralized dt_table on the search path as a FALLBACK (below globalenv):
# a user's own `dt_table <- ...` shadows this; rm("dt_table") removes the user's, then
# this is used again. Not listed by ls(.GlobalEnv). (r-cell lesson: DT htmlwidgets open
# a browser and block/error headless; the kable version is a safe fallback.)
attach(list(dt_table = .repl$dt_table_impl), name = "interactive-repl:helpers",
       warn.conflicts = FALSE)
on.exit(detach("interactive-repl:helpers"), add = TRUE)

.repl$run_cell <- function(code) {
  out <- ""; plots <- character(0); warns <- character(0)
  stdout_con <- textConnection("out", "w", local = TRUE)
  sink(stdout_con, type = "output")
  error_msg <- tryCatch({
    ex <- parse(text = code)
    for (i in seq_along(ex)) {
      r <- withCallingHandlers(
        withVisible(eval(ex[[i]], envir = globalenv())),
        warning = function(w) {
          warns <<- c(warns, conditionMessage(w))
          invokeRestart("muffleWarning")
        }
      )
      if (isTRUE(r$visible)) {
        if (inherits(r$value, "ggplot")) {
          f <- tempfile(pattern = "fig-", fileext = ".png", tmpdir = .repl$plot_dir())
          tryCatch(ggplot2::ggsave(f, r$value, width = 12, height = 8, dpi = 110),
                   error = function(e) NULL)
          plots <- c(plots, f)
          cat("FIGURE saved:", f, "\n")
        } else {
          print(r$value)
        }
      }
    }
    NULL
  }, error = function(e) conditionMessage(e))
  sink(); close(stdout_con)
  out_text <- paste(out, collapse = "\n")  # character(0) → "" (nzchar-safe)
  if (!nzchar(out_text) && !is.null(error_msg)) out_text <- paste0("ERROR: ", error_msg)
  list(stdout = out_text, stderr = paste(warns, collapse = "\n"),
       error = error_msg, plots = as.list(plots),
       truncated = FALSE, degraded = FALSE)
}

# Ready marker: job info from srun's env (read by the server over stdout).
.repl$write_json(list(ready = TRUE,
                      job_id = Sys.getenv("SLURM_JOB_ID"),
                      node = Sys.getenv("SLURM_JOB_NODELIST")))

# Main loop inside a function so req/res/rid/line are not exposed in globalenv (else
# list_variables would leak them). .repl (dot-prefixed, in globalenv) is reachable as
# the function's enclosing env.
.repl$run_loop <- function() {
  repeat {
    line <- tryCatch(readLines(.repl$con_in, n = 1),
                     error = function(e) character(0),
                     warning = function(w) character(0))
    if (length(line) == 0) break  # EOF / stdin closed
    line <- line[nzchar(line)]
    if (length(line) == 0) next
    req <- tryCatch(jsonlite::fromJSON(line), error = function(e) NULL)
    if (is.null(req)) {
      .repl$write_json(list(id = "unknown", stdout = "", stderr = "", error = "Invalid JSON",
                            plots = as.list(character(0)), truncated = FALSE, degraded = FALSE))
      next
    }
    rid <- if (is.null(req$id) || length(req$id) == 0) "unknown" else req$id
    res <- tryCatch(.repl$run_cell(req$code), error = function(e) {
      list(stdout = "", stderr = "", error = conditionMessage(e),
           plots = as.list(character(0)), truncated = FALSE, degraded = FALSE)
    })
    res$id <- rid
    .repl$write_json(res)
  }
}
.repl$run_loop()
```

- [ ] **Step 4: Rewrite `scripts/python_worker.py` protocol parts**

Header comment (lines 7-16) becomes:

```python
"""Persistent Python namespace over a JSON-per-line stdin/stdout protocol.

Request:  {"id": "<rid>", "code": "<python source>"}
Response: {"id": "<rid>", "stdout": "...", "stderr": "...", "error": null|"<traceback>",
           "plots": ["/path/to/fig.png"], "truncated": false, "degraded": false}

Protocol channel: stdio pipes — local and slurm alike, because slurm runs this
worker via salloc+srun, which forwards the pipes to the compute node. Protocol
pipes are duped off fd 0/1 so user subprocesses inheriting them can't corrupt
the stream; real stdin/stdout → devnull. Errors are caught — the response
ALWAYS returns (no hangs). Adapted from wisp-science's kernel_worker.py.
"""
```

In `main()`, replace the transport branch (the `port = os.environ.get("REPL_PORT")` block through the fd-dup, old lines 162-192) with:

```python
def main():
    # Protocol channel: stdio pipes. Real stdin/stdout → devnull so user
    # subprocesses inheriting them can't corrupt the stream.
    protocol_in = os.fdopen(os.dup(0), "r", encoding="utf-8", errors="replace")
    protocol_out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
```

Ready marker (old lines 220-228): remove the token line:

```python
    protocol_out.write(_common.encode_line({
        "ready": True,
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "node": os.environ.get("SLURM_JOB_NODELIST"),
    }))
```

- [ ] **Step 5: Rewrite `scripts/_slurm.py` (full file)**

```python
#!/usr/bin/env python3
# Shared Slurm/HPC launch helpers for the repl MCP server.
#
# Slurm mode is active when INTERACTIVE_REPL_SLURM (srun flags string) is set
# or the worker_mode tool overrode the mode. A worker is launched as
# `salloc <flags> srun <flags> <worker cmd>`: salloc holds the allocation, srun
# forwards the worker's stdio pipes to the login node, so the JSON protocol
# rides plain pipes — no ports, no tokens, no ssh tunnels. Already inside an
# allocation (SLURM_JOB_ID set): a bare `srun` attaches to it.
"""Slurm launch helpers: launch, probe, config resolution."""
import os, shlex, shutil, subprocess

_DEFAULT_TIMEOUT = 300
_runtime: dict = {}  # worker_mode tool overrides: {"mode", "flags"}


def set_runtime(mode=None, flags=None):
    """Record worker_mode tool overrides. "" / None = no override (keep env)."""
    if mode is not None:
        _runtime["mode"] = mode
    if flags:
        _runtime["flags"] = flags


def reset_runtime():
    """Drop tool overrides (fresh server instance = env defaults again)."""
    _runtime.clear()


def slurm_enabled() -> bool:
    """True if sessions should launch via salloc/srun. A tool mode override
    beats env; mode="local" disables slurm even when INTERACTIVE_REPL_SLURM
    is set."""
    if "mode" in _runtime:
        return _runtime["mode"] == "slurm"
    return bool(os.environ.get("INTERACTIVE_REPL_SLURM"))


def flags() -> str:
    return _runtime.get("flags", os.environ.get("INTERACTIVE_REPL_SLURM", ""))


def srun_timeout() -> int:
    try:
        return int(os.environ.get("INTERACTIVE_REPL_SRUN_TIMEOUT", _DEFAULT_TIMEOUT))
    except ValueError:
        return _DEFAULT_TIMEOUT


def srun_cmd(flags_str: str, cmd: list[str]) -> list[str]:
    return ["srun", *shlex.split(flags_str), *cmd]


def probe() -> dict:
    """Environment detection for the worker_mode tool's decision logic."""
    return {
        "srun_available": shutil.which("srun") is not None,
        "already_in_allocation": bool(os.environ.get("SLURM_JOB_ID")),
    }


def launch(worker_cmd: list[str]) -> subprocess.Popen:
    """Launch a worker on a compute node: `salloc <flags> srun <flags>
    <worker>` (or bare `srun <flags> <worker>` when already inside an
    allocation). srun forwards the worker's stdio pipes, so the JSON protocol
    rides them unchanged. Returns the Popen; the server reads the ready
    handshake with the srun_timeout deadline (queue wait)."""
    if os.environ.get("SLURM_JOB_ID"):
        argv = srun_cmd(flags(), worker_cmd)
    else:
        argv = ["salloc", *shlex.split(flags()), *srun_cmd(flags(), worker_cmd)]
    try:
        return subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1)
    except OSError as e:
        raise RuntimeError(f"could not launch {argv[0]}: {e}")
```

- [ ] **Step 6: Edit `scripts/repl_server.py`**

(a) Imports (line 11): `import json, os, socket, subprocess, sys, uuid` → `import json, os, selectors, subprocess, sys, time, uuid`

(b) `_Session` (lines 27-37):

```python
class _Session:
    """One worker. Local mode: proc pipes carry the protocol. Slurm mode:
    the same pipes are forwarded by the salloc/srun chain; job_id/node come
    from the worker's ready handshake (SLURM_JOB_ID / SLURM_JOB_NODELIST)."""

    def __init__(self, proc, job_id=None, node=None):
        self.proc = proc
        self.job_id = job_id
        self.node = node
```

(c) `SessionInfo` (lines 87-95): remove the `transport: str = "local"` field.

(d) `Probe` (lines 122-126):

```python
class Probe(BaseModel):
    srun_available: bool = False
    already_in_allocation: bool = False
```

(e) `WorkerModeInfo` (lines 128-136): remove `transport` and `host`:

```python
class WorkerModeInfo(BaseModel):
    mode: str
    source: str
    slurm_flags: str = ""
    timeout: int = 300
    probe: Probe
```

(f) Add `_py_worker_cmd` before `_r_worker_cmd` (before line 169):

```python
def _py_worker_cmd() -> list:
    """The py worker's interpreter: INTERACTIVE_REPL_PY_BIN (a project's
    conda-env python) or the server's own interpreter."""
    py_bin = os.environ.get("INTERACTIVE_REPL_PY_BIN")
    return [py_bin or sys.executable, str(WORKER)]
```

(g) `_r_worker_cmd` (lines 169-174) — add `--quiet --no-echo`:

```python
def _r_worker_cmd() -> list:
    r_env = os.environ.get("INTERACTIVE_REPL_R_ENV")
    r_bin = os.environ.get("INTERACTIVE_REPL_R_BIN", "R")
    argv = [r_bin, "--quiet", "--no-echo", "--no-save", "--no-restore", "-f", str(REPL_R)]
    return (["conda", "run", "-n", r_env, "--no-capture-output", *argv]
            if r_env else argv)
```

(h) `_LANGUAGES` (lines 179-197) — drop the `tcp` keys, py cmd uses the function:

```python
_LANGUAGES = {
    "py": {
        "cmd": _py_worker_cmd,
        "list_vars": _LIST_VARS_PY,
        "inspect": lambda name, path: f"print(repr({name}{''.join(f'[{p!r}]' for p in path)}))",
        "sidecar": "kernel.py",
    },
    "r": {
        "cmd": _r_worker_cmd,
        "list_vars": _LIST_VARS_R,
        "inspect": lambda name, path: (
            f"print(str({name}{''.join(f'[[{p!r}]]' for p in path)})); "
            f"print(utils::head({name}{''.join(f'[[{p!r}]]' for p in path)}, 10))"
        ),
        "sidecar": "kernel.R",
    },
}
```

(i) `_send` / `_recv` (lines 211-231):

```python
def _send(s: _Session, line: str) -> None:
    s.proc.stdin.write(line)
    s.proc.stdin.flush()


def _recv(s: _Session, rid: str) -> dict:
    """Read one response line whose id matches rid, skipping any non-JSON
    garbage (R child-process output leaking onto stdout)."""
    for _ in range(10000):  # sanity cap — a garbage flood shouldn't loop forever
        line = s.proc.stdout.readline()
        if not line:
            raise OSError("pipe closed")
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("id") == rid:
            return obj
    raise OSError("too much non-protocol output")
```

(j) Add `_read_ready` before `_start` and replace `_start` (lines 234-281):

```python
def _read_ready(proc, timeout: float, hint: str) -> dict:
    """Read the worker's ready handshake: the first line on stdout that parses
    as JSON with a "ready" key, tolerant of stray banner/output lines, with a
    deadline. Raises RuntimeError with the hint on timeout/EOF."""
    sel = selectors.DefaultSelector()
    sel.register(proc.stdout, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    buf = ""
    while time.monotonic() < deadline:
        if not sel.select(max(0.0, deadline - time.monotonic())):
            break
        chunk = os.read(proc.stdout.fileno(), 65536)
        if not chunk:
            break
        buf += chunk.decode(errors="replace")
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            try:
                obj = json.loads(line.strip())
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("ready") is not None:
                return obj
    raise RuntimeError(hint)


def _start(lang: str, bare: str) -> _Session:
    spec = _LANGUAGES[lang]
    cmd = spec["cmd"]()
    if _slurm.slurm_enabled():
        proc = _slurm.launch(cmd)
        timeout = _slurm.srun_timeout()
        hint = (f"salloc allocation did not start within {timeout}s — check "
                f"INTERACTIVE_REPL_SLURM flags and queue status (squeue). "
                f"First call blocks until the allocation starts.")
    else:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1)
        timeout = 30
        hint = f"worker failed to start within {timeout}s"
    try:
        ready = _read_ready(proc, timeout, hint)
        if not ready.get("ready"):
            proc.terminate()
            raise RuntimeError(f"worker failed to start: {ready!r}")
    except RuntimeError:
        proc.terminate()
        raise
    s = _Session(proc, job_id=ready.get("job_id"), node=ready.get("node"))
    # Auto-inject the base sidecar so _peek/_who/_fig are available immediately.
    base = _base_sidecar_src(lang)
    if base:
        _send(s, _common.encode_line({"id": "init", "code": base}))
        _recv(s, "init")  # discard the init response
    return s
```

(k) `_call_worker` (lines 296-318) — return the parsed response:

```python
def _call_worker(session: str, code: str) -> dict:
    parsed = _parse_session(session)
    if parsed is None:
        return {"stdout": "", "stderr": "", "error": _AMBIG,
                "plots": [], "truncated": False, "degraded": False}
    lang, bare = parsed
    rid = uuid.uuid4().hex
    try:
        s = _get(lang, bare)
        _send(s, _common.encode_line({"id": rid, "code": code}))
        return _recv(s, rid)
    except (BrokenPipeError, OSError) as e:
        _sessions.pop(f"{lang}:{bare}", None)
        return {"stdout": "", "stderr": "", "error": f"worker died: {e}",
                "plots": [], "truncated": False, "degraded": False}
    except RuntimeError as e:
        # session-start failures (queue timeout, worker refused to start)
        # surface as structured errors — raising here hangs the MCP request
        # in the in-process client (exceptions are not auto-converted).
        _sessions.pop(f"{lang}:{bare}", None)
        return {"stdout": "", "stderr": "", "error": str(e),
                "plots": [], "truncated": False, "degraded": False}
```

(l) `_kill` (in the close/restart area, lines 321-341): remove the conn branch:

```python
def _kill(s: _Session) -> bool:
    """Teardown one session's worker: scancel (slurm), terminate the process.
    Returns True if a live worker was killed."""
    if s.proc.poll() is not None:
        return False
    if s.job_id:
        try:
            subprocess.run(["scancel", s.job_id], timeout=10, capture_output=True)
        except Exception:
            pass
    try:
        s.proc.terminate(); s.proc.wait(timeout=2)
    except Exception:
        pass
    return True
```

(m) `session_info` (lines 419-434): drop transport from the return:

```python
@mcp.tool()
def session_info(session: str) -> SessionInfo:
    """Report whether the named session is running, its pid, the plot dir, and
    (slurm mode) the compute-node job id / node."""
    parsed = _parse_session(session)
    if parsed is None:
        return SessionInfo(session=session, running=False, error=_AMBIG)
    lang, bare = parsed
    s = _sessions.get(f"{lang}:{bare}")
    running = s is not None and s.proc.poll() is None
    return SessionInfo(session=session, running=running,
                       pid=s.proc.pid if running else None,
                       plot_dir=_common.plot_dir(),
                       job_id=s.job_id if running else None,
                       node=s.node if running else None)
```

(n) `worker_mode` (lines 437-462): drop transport + host, adjust docstring:

```python
@mcp.tool()
def worker_mode(mode: str = None, slurm_flags: str = None) -> WorkerModeInfo:
    """Get or set how this server launches workers. No args = probe the
    environment (srun present? already inside a job?) and report the current
    mode and its source ("env" default or "tool" override). mode="local"|"slurm"
    switches; slurm_flags overrides INTERACTIVE_REPL_SLURM (omit or pass "" to
    keep the env default). Slurm workers launch as `salloc <flags> srun
    <worker>` (or bare `srun` when already inside an allocation), protocol
    over stdio pipes. Tool settings apply to sessions created after the switch
    (existing sessions keep running until restart) and reset when the server
    restarts."""
    if mode is not None:
        _slurm.set_runtime(mode=mode)
    if slurm_flags is not None:
        _slurm.set_runtime(flags=slurm_flags)
    return WorkerModeInfo(
        mode="slurm" if _slurm.slurm_enabled() else "local",
        source="tool" if "mode" in _slurm._runtime else "env",
        slurm_flags=_slurm.flags(),
        timeout=_slurm.srun_timeout(),
        probe=Probe(**_slurm.probe()),
    )
```

- [ ] **Step 7: Run the FULL suite — all green**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/ -q`
Expected: **141 passed** (148 − 9 deleted + 2 added), 0 failed.

- [ ] **Step 8: Commit**

```bash
git add data-science/interactive-repl/scripts/repl.R data-science/interactive-repl/scripts/python_worker.py data-science/interactive-repl/scripts/_slurm.py data-science/interactive-repl/scripts/repl_server.py data-science/interactive-repl/tests/
git commit -m "feat: stdio-only transport — salloc+srun workers, TCP/token/tunnel removed"
```

---

### Task 2: project-scoped env config (PY_BIN + versioned py-site)

**Files:**
- Modify: `data-science/interactive-repl/scripts/python_worker.py` (versioned `_py_site_dir`)
- Modify: `data-science/interactive-repl/scripts/repl_server.py` (`_py_worker_cmd` already reads `INTERACTIVE_REPL_PY_BIN` from Task 1 — no change needed here)
- Modify: `data-science/interactive-repl/scripts/setup.sh` (versioned SITE_DIR)
- Modify: `data-science/interactive-repl/scripts/discover.py` (settings.local.json guidance)
- Modify: `data-science/interactive-repl/tests/test_python_worker.py`, `tests/test_python_server.py`

- [ ] **Step 1: Write the failing tests**

**test_python_worker.py** — update the two py-site assertions to the versioned dir:

`test_lazy_install_invokes_uv_pip_target` (lines 104-116): replace the two `py-site` assertions:

```python
    site_dir = f"py-site-{sys.version_info.major}.{sys.version_info.minor}"
    assert str(tmp_path / site_dir) in cmd
    assert str(tmp_path / site_dir) in sys.path   # added so the retry import finds it
```

`test_worker_uses_preinstalled_py_site` (lines 215-228):

```python
def test_worker_uses_preinstalled_py_site(monkeypatch, tmp_path):
    """A py-site-<ver> pre-populated by scripts/setup.sh is on sys.path from
    the start — imports work without the lazy-install hook re-fetching."""
    site = tmp_path / f"py-site-{sys.version_info.major}.{sys.version_info.minor}"
    site.mkdir()
    (site / "preinstalled_marker.py").write_text("VALUE = 'preinstalled'\n")
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    p = _spawn()
    try:
        r = _call(p, "import preinstalled_marker; print(preinstalled_marker.VALUE)")
        assert r["error"] is None
        assert "preinstalled" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()
```

**test_python_server.py** — append:

```python
@pytest.mark.asyncio
async def test_py_bin_env_selects_interpreter(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    shim = tmp_path / "py-shim"
    shim.write_text("#!/bin/sh\nexec %s \"$@\"\n" % sys.executable)
    shim.chmod(0o755)
    monkeypatch.setenv("INTERACTIVE_REPL_PY_BIN", str(shim))
    from mcp import Client
    from repl_server import mcp, _sessions
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "py:pybin1", "code": "1 + 1"})
        assert r.structured_content["error"] is None
        assert "2" in r.structured_content["stdout"]
    assert _sessions["py:pybin1"].proc.args[0] == str(shim)  # env selected the interpreter
```

(`test_python_server.py` needs `import sys` at the top — add it if missing.)

- [ ] **Step 2: Run the new tests — they FAIL**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_worker.py tests/test_python_server.py -k "py_site or py_bin" -v`
Expected: 3 failures (worker still uses `py-site`; `_py_worker_cmd` ignores PY_BIN — actually it does NOT: Task 1 already wired PY_BIN. Check: if `test_py_bin_env_selects_interpreter` already passes, that's fine — the versioned-py-site tests are the red ones.)

- [ ] **Step 3: Implement — `python_worker.py` `_py_site_dir` (lines 116-119)**

```python
def _py_site_dir():
    # Wheels are interpreter-ABI-specific — key the dir by interpreter version
    # so a worker launched with a different python (INTERACTIVE_REPL_PY_BIN)
    # never imports stale wrong-ABI wheels from another version's dir.
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    d = os.path.join(_data_dir(), f"py-site-{ver}")
    os.makedirs(d, exist_ok=True)
    return d
```

Also update the pre-add in `main()` (old lines 202-204) — the dir is now versioned via `_py_site_dir()`:

```python
    _site = _py_site_dir()
    if os.path.isdir(_site) and os.listdir(_site):
        sys.path.insert(0, _site)
```

(The lazy-install hook already calls `_py_site_dir()` — it picks up the versioned dir automatically.)

- [ ] **Step 4: `scripts/setup.sh` — versioned install dir (lines 23-24)**

```bash
# py-site wheels are interpreter-version-specific (uv builds them for the
# interpreter uv run resolves — the same one the workers use by default).
# The dir is version-keyed (py-site-<major>.<minor>) so a worker launched
# with a different interpreter (INTERACTIVE_REPL_PY_BIN) never imports stale
# wrong-ABI wheels from another version's dir.
PY_VER=$(uv run --no-project python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null \
        || python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null \
        || echo "3")
SITE_DIR="${CLAUDE_PLUGIN_DATA:-/tmp/interactive-repl-data}/py-site-${PY_VER}"
```

- [ ] **Step 5: `scripts/discover.py` — guidance points at project-level config**

Replace the "Next steps" block in `print_report` (lines 266-291):

```python
    print("Next steps")
    r_ready = [c for c in cands if c.language == "r" and c.usable]
    if r_ready:
        best = r_ready[0]
        if best.kind == "conda":
            print(f"  r: INTERACTIVE_REPL_R_ENV={best.env_name}   "
                  f"(best candidate: {best.display_name()})")
        else:
            print(f"  r: INTERACTIVE_REPL_R_BIN={best.path}   "
                  f"(best candidate: {best.display_name()})")
    else:
        creator = "mamba" if shutil.which("mamba") else ("conda" if shutil.which("conda") else "")
        if creator:
            print(f"  r: no usable R — create one: {creator} create -n r-env "
                  f"-c conda-forge r-base r-jsonlite r-knitr r-ggplot2")
        else:
            print("  r: no usable R and no conda/mamba — install R (see references/r-setup.md)")
    py_ready = [c for c in cands if c.language == "python" and c.usable]
    if not py_ready:
        print("  py: no python found — run scripts/setup.sh (installs uv + deps)")
    else:
        best = py_ready[0]
        missing = [p for p, ok in best.packages.items() if not ok]
        if missing:
            print(f"  py: best candidate {best.display_name()} lacks "
                  f"{', '.join(missing)} — run scripts/setup.sh to install them into py-site")
    print("  Write the chosen env into THIS project's .claude/settings.local.json "
          "(env section), e.g. {\"env\": {\"INTERACTIVE_REPL_R_ENV\": \"...\"}} — "
          "ask the user which env to use; never ~/.bashrc.")
```

- [ ] **Step 6: Run the FULL suite — all green**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/ -q`
Expected: **142 passed** (141 + 1 new PY_BIN test), 0 failed.

- [ ] **Step 7: Commit**

```bash
git add data-science/interactive-repl/scripts/python_worker.py data-science/interactive-repl/scripts/setup.sh data-science/interactive-repl/scripts/discover.py data-science/interactive-repl/tests/test_python_worker.py data-science/interactive-repl/tests/test_python_server.py
git commit -m "feat: project-scoped env config — INTERACTIVE_REPL_PY_BIN + versioned py-site"
```

---

### Task 3: docs sweep

**Files:**
- Modify: `data-science/interactive-repl/SKILL.md`
- Modify: `data-science/interactive-repl/references/tools.md`
- Modify: `data-science/interactive-repl/references/slurm-hpc.md`
- Modify: `data-science/interactive-repl/references/r-setup.md`

- [ ] **Step 1: SKILL.md — Setup step 2 mentions the versioned dir**

Change (line 39): `into the worker's \`py-site\` in a single \`uv pip install --target\`` → `into the worker's version-keyed \`py-site-<ver>\` in a single \`uv pip install --target\``

- [ ] **Step 2: SKILL.md — rewrite Setup step 3 (lines 42-53) to the ask-then-project-config flow**

```markdown
3. **Environments — ask the user, then write project-level config.** Run the
   skill's discovery scanner `scripts/discover.py` (Positron-style multi-source:
   PATH, conda envs via `conda env list --json` with `~/.conda/environments.txt`
   fallback, uv-managed pythons, system dirs like `/opt/R`; it probes every
   candidate's version + the packages this skill needs, marks broken ones but
   keeps scanning). Then **ask the user** which env to use in THIS project —
   conda envs are project-scoped, so never guess and never write global config:
   - **R**: which conda env / R path? Configure with `INTERACTIVE_REPL_R_ENV`
     (conda env name) or `INTERACTIVE_REPL_R_BIN` (path to R).
   - **Python**: which conda env's python, or the server default (any usable
     python works — missing deps are installed by `scripts/setup.sh` into the
     versioned `py-site-<ver>`, never a blocker)? Configure with
     `INTERACTIVE_REPL_PY_BIN` (env's python path) if a specific env was chosen.
   - Write the choice into the **project-level** `.claude/settings.local.json`
     `env` section — never `~/.bashrc` (that pollutes every other project):
     `{"env": {"INTERACTIVE_REPL_R_ENV": "r-env"}}`. Ask whether the user also
     wants a user-level copy; default is project-level only.
   - If nothing is READY: use the create command discover.py prints (`mamba
     create -n r-env -c conda-forge r-base r-jsonlite r-knitr r-ggplot2`),
     then re-run discovery.
   - Tell the user to restart Claude Code — the server reads these env vars at
     launch.
```

- [ ] **Step 3: SKILL.md — tool descriptions drop transport**

`session_info` line (105): `... compute-node job id / node / transport.` → `... compute-node job id / node.`

`worker_mode` line (106): keep (no transport mention).

- [ ] **Step 4: SKILL.md — HPC section drops ssh_available**

Change (line 141): `(\`srun_available\`, \`already_in_allocation\`, \`ssh_available\`)` → `(\`srun_available\`, \`already_in_allocation\`)`

- [ ] **Step 5: `references/tools.md` — close + session_info wording**

`close` section (lines 71-72): `closes the transport, terminates the process, and (slurm mode) scancels the allocation` → `terminates the process and (slurm mode) scancels the allocation`.

`session_info` section (78-83) — the JSON example is already correct (no transport); leave as-is.

- [ ] **Step 6: `references/slurm-hpc.md` — full rewrite**

```markdown
# HPC / Slurm — run REPL workers on compute nodes

At HPC centers, login nodes must not run long or compute-heavy work — compute
belongs on a compute node. This skill launches each REPL worker via
`salloc <flags> srun <flags> <worker>`: salloc holds the allocation, srun
forwards the worker's stdio pipes to the login node, so the JSON protocol
rides plain pipes — no ports, no tokens, no ssh tunnels. Off by default;
activate via `worker_mode()` (runtime) or `INTERACTIVE_REPL_SLURM` (persistent).

## When to use

- The task is heavy (big joins, training, simulations) and the host is a login node.
- The user mentions 超算/集群/slurm/srun/sbatch/队列/配额/partition.
- `worker_mode()` reports `probe.srun_available: true` and the task is heavy.

## Decision flow — call `worker_mode()` with no args first

1. `probe.srun_available: false` → stay `local`; tell the user this host has no Slurm.
2. `probe.already_in_allocation: true` → the server launches a bare `srun` —
   Claude Code is already inside a job; the worker attaches to the allocation.
3. Otherwise, for heavy work → `worker_mode(mode="slurm")`. Flags: use the
   user's partition/account/cpus/mem if they told you, else pass nothing
   (keeps the env default).
4. Session over / task turned light → `worker_mode(mode="local")` to stop
   submitting jobs.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `INTERACTIVE_REPL_SLURM` | unset | salloc/srun flags, e.g. `--partition=compute --account=acct -c 16 --mem=64G`. Non-empty → all sessions of this server launch via salloc+srun. |
| `INTERACTIVE_REPL_SRUN_TIMEOUT` | `300` | Max queue wait + startup (seconds). |

`worker_mode()` overrides at runtime (per server process); tool settings beat
env vars, apply to sessions created after the switch, and reset when the
server restarts.

## Prerequisites — read before using

1. **`CLAUDE_PLUGIN_DATA` must point at shared storage.** The default
   `/tmp/interactive-repl-data` is per-node: plots saved on a compute node
   would be invisible on the login node, and the lazy-install `py-site-<ver>`
   would be built twice. Export it to a shared path (e.g. under your home)
   before using slurm mode.
2. Login and compute nodes share home (standard on HPC) — this is what makes
   the worker scripts, the uv-managed python, R/conda envs and `uv` available
   on the compute node. No ssh or port-forwarding setup is needed: srun
   carries the stdio itself.

## Semantics

- **First call blocks**: `run_code` auto-creates the session, which submits
  the salloc+srun chain and waits for the allocation
  (`INTERACTIVE_REPL_SRUN_TIMEOUT`). Queue wait is real — tell the user the
  session is queued.
- **Allocation expiry ≈ data loss.** The allocation's time limit bounds the
  session. When the allocation ends the pipes close — `run_code` returns
  `worker died`; `restart(session)` resubmits (a fresh namespace). Size the
  allocation for the work.
- **`restart` / `close`** scancel the old job (job id from the worker's ready
  handshake) and kill the salloc process.
- **`session_info`** reports `job_id` / `node` — tell the user where the
  session runs ("on cn042, job 74213").
- **Switching modes** only affects new sessions; existing sessions keep
  running until restarted.

## Common failures

- `salloc allocation did not start within 300s` — flags wrong (bad
  partition/account) or queue busy; check `squeue`, fix flags, retry.
- `worker died` mid-session — allocation expired or was preempted → `restart`.
- Plots not readable after slurm sessions — `CLAUDE_PLUGIN_DATA` is not on
  shared storage (see Prerequisites).

## Escape hatch

Run the entire Claude Code inside `srun --pty` — everything stays localhost
and zero configuration is needed. Use it when the whole session belongs on a
compute node; use slurm mode when you work on the login node and compute on
nodes.
```

- [ ] **Step 7: `references/r-setup.md` — protocol note + config location**

Replace the "Configure the server" block (lines 28-35):

```markdown
Configure the server per-project — write into the project's
`.claude/settings.local.json` `env` section (never `~/.bashrc` — conda envs
are project-scoped; ask the user which env to use):

```jsonc
{ "env": { "INTERACTIVE_REPL_R_ENV": "<env>" } }   // or "INTERACTIVE_REPL_R_BIN"
```

The server reads these env vars at launch, so restart Claude Code after
changing them.
```

Replace line 73-74: `Set per-project via \`.claude/settings.json\` \`env\` or your shell env.` → `Set per-project via \`.claude/settings.local.json\` \`env\`.`.

In "R + packages" (line 51): `An \`r:\` session spawns \`R --no-save --no-restore\` running \`scripts/repl.R\`.` → `An \`r:\` session spawns \`R --quiet --no-echo --no-save --no-restore\` running \`scripts/repl.R\` — the protocol is JSON-per-line over stdio (stdin/stdout pipes); warnings surface in the response's \`stderr\` field.`

- [ ] **Step 8: Verify SKILL.md stays within limits**

Run (from repo root): `./count-skill-tokens.py data-science/interactive-repl`
Expected: SKILL.md under 500 lines / 5,000 tokens; description under 100 tokens (unchanged at 93).

- [ ] **Step 9: Commit**

```bash
git add data-science/interactive-repl/SKILL.md data-science/interactive-repl/references/tools.md data-science/interactive-repl/references/slurm-hpc.md data-science/interactive-repl/references/r-setup.md
git commit -m "Docs: project-scoped config flow + stdio-only transport"
```
