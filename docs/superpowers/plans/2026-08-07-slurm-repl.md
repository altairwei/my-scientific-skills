# Slurm / HPC Worker Launch — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Slurm/HPC support to `interactive-repl`: when configured (env `INTERACTIVE_REPL_SLURM` or the new `worker_mode` tool), each REPL worker launches inside an `srun` allocation on a compute node and connects back to the server on the login node via direct TCP or an ssh `-L` tunnel, with a token handshake.

**Architecture:** A new shared module `_slurm.py` encapsulates all slurm mechanics (srun spawn, bind+token+accept handshake, tunnel cmd, probe, runtime-override config). The python worker gains a TCP-client protocol path (pipes stay for local mode); `repl.R` gains `REPL_HOST`, a tunnel branch, and token in the ready message. Both servers branch `_start()`/`restart()`/`session_info()` on slurm mode and expose the new `worker_mode` tool. Local mode is byte-for-byte unchanged.

**Tech Stack:** Python 3.10+ stdlib (`socket`, `secrets`, `shlex`, `shutil`), R (existing), pytest/pytest-asyncio (existing). No new deps. Slurm/ssh are NOT required for tests — fake `srun`/`scancel`/`ssh` shims on a temp PATH.

**Spec:** `docs/superpowers/specs/2026-08-07-slurm-repl-design.md` — read it for the *why*.

**Existing patterns (verified):** Both servers import shared `_common`/`_chunk_parser` from `scripts/` via `sys.path.insert(0, str(HERE))` (line 18-19 of both servers). The R server already has the full TCP pattern this feature generalizes: bind → Popen with env → accept → read ready line → sidecar inject. `python_repl_server._start` (lines 116-131) Popen's the worker with pipes; `_call_worker` (142-157) writes `_common.encode_line` and reads one line. Tests use `monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))` then `from mcp import Client; async with Client(mcp) as client:` + `client.call_tool(...)`.

**Bash cwd trap (learned the hard way):** the Bash tool's cwd persists between calls — always `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && ...` explicitly, or the tests run from the repo root and pytest collects 0 items.

Test command (from the skill root):
```bash
cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/ -v
```

---

## File Structure

```
data-science/interactive-repl/
├── scripts/
│   ├── _slurm.py                  # NEW — launch_remote, tunnel_cmd, probe, runtime config
│   ├── python_worker.py           # MODIFIED — TCP-client path (direct), tunnel branch (Task 6)
│   ├── repl.R                     # MODIFIED — REPL_HOST, token in ready (Task 3), tunnel (Task 6)
│   ├── python_repl_server.py      # MODIFIED — _Session struct, slurm _start/_call_worker/restart/session_info, worker_mode tool
│   └── r_repl_server.py           # MODIFIED — slurm _start/restart/session_info, worker_mode tool
├── references/
│   ├── slurm-hpc.md               # NEW
│   └── troubleshooting.md         # MODIFIED — Slurm/HPC section
├── SKILL.md                       # MODIFIED — worker_mode bullet + HPC/Slurm section
├── README.md                      # MODIFIED (repo root) — interactive-repl row + MCP paragraph
└── tests/
    ├── test_slurm.py              # NEW — _slurm unit tests, fake-srun/shims integration (both servers), tunnel, worker_mode
    └── test_python_worker.py      # MODIFIED — TCP-mode tests
```

---

## Task 1: `_slurm.py` shared module + unit tests

**Files:**
- Create: `data-science/interactive-repl/scripts/_slurm.py`
- Test: `data-science/interactive-repl/tests/test_slurm.py` (create with unit tests only; integration tests are added in later tasks)

- [ ] **Step 1: Write the failing tests (create `tests/test_slurm.py`)**

```python
import os
import re
import socket
import sys
import pathlib
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import _slurm  # noqa: E402


def test_srun_cmd_parses_flags():
    assert _slurm.srun_cmd("--partition=a -c 8", ["python", "w.py"]) == \
        ["srun", "--partition=a", "-c", "8", "python", "w.py"]


def test_srun_cmd_empty_flags():
    assert _slurm.srun_cmd("", ["x"]) == ["srun", "x"]


def test_new_token_is_32_hex_chars():
    assert re.fullmatch(r"[0-9a-f]{32}", _slurm.new_token())


def test_login_host_env_override(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "my-login")
    assert _slurm.login_host() == "my-login"


def test_login_host_defaults_to_gethostname(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_REPL_HOST", raising=False)
    assert _slurm.login_host() == socket.gethostname()


def test_srun_timeout_default_and_parse(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_REPL_SRUN_TIMEOUT", raising=False)
    assert _slurm.srun_timeout() == 300
    monkeypatch.setenv("INTERACTIVE_REPL_SRUN_TIMEOUT", "600")
    assert _slurm.srun_timeout() == 600
    monkeypatch.setenv("INTERACTIVE_REPL_SRUN_TIMEOUT", "abc")
    assert _slurm.srun_timeout() == 300


def test_tunnel_cmd_argv():
    cmd = _slurm.tunnel_cmd(43210, "login01", 45678)
    assert cmd[0] == "ssh"
    assert "-L" in cmd
    assert "43210:localhost:45678" in cmd
    assert "login01" in cmd
    assert "BatchMode=yes" in cmd
    assert "ExitOnForwardFailure=yes" in cmd


def test_slurm_enabled_env(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_REPL_SLURM", raising=False)
    _slurm.reset_runtime()
    assert _slurm.slurm_enabled() is False
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=test")
    assert _slurm.slurm_enabled() is True


def test_runtime_mode_local_overrides_env(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=test")
    _slurm.set_runtime(mode="local")
    assert _slurm.slurm_enabled() is False
    _slurm.reset_runtime()
    assert _slurm.slurm_enabled() is True


def test_flags_precedence_runtime_over_env(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=env")
    _slurm.reset_runtime()
    assert _slurm.flags() == "--partition=env"
    _slurm.set_runtime(flags="--partition=tool")
    assert _slurm.flags() == "--partition=tool"
    _slurm.reset_runtime()
    assert _slurm.flags() == "--partition=env"


def test_flags_empty_or_none_keeps_env(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=env")
    _slurm.reset_runtime()
    _slurm.set_runtime(flags="")
    assert _slurm.flags() == "--partition=env"   # empty string = keep env (spec)
    _slurm.set_runtime(flags=None)
    assert _slurm.flags() == "--partition=env"


def test_transport_default_and_override(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_REPL_TRANSPORT", raising=False)
    _slurm.reset_runtime()
    assert _slurm.transport() == "direct"
    monkeypatch.setenv("INTERACTIVE_REPL_TRANSPORT", "tunnel")
    assert _slurm.transport() == "tunnel"
    _slurm.set_runtime(transport="direct")
    assert _slurm.transport() == "direct"   # tool beats env
    _slurm.reset_runtime()


def test_probe_fields(monkeypatch, tmp_path):
    srun_shim = tmp_path / "srun"
    srun_shim.write_text("#!/bin/sh\nexit 0\n")
    srun_shim.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    p = _slurm.probe()
    assert p["srun_available"] is True
    assert p["already_in_allocation"] is False
    monkeypatch.setenv("SLURM_JOB_ID", "1234")
    assert _slurm.probe()["already_in_allocation"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio python -m pytest tests/test_slurm.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named '_slurm'` (script doesn't exist yet).

- [ ] **Step 3: Implement `scripts/_slurm.py`**

```python
#!/usr/bin/env python3
# data-science/interactive-repl/scripts/_slurm.py
# Shared Slurm/HPC launch helpers for the python-repl and r-repl MCP servers.
#
# Slurm mode is active when INTERACTIVE_REPL_SLURM (srun flags string) is set
# or the worker_mode tool overrode the mode. A worker is launched with
# `srun <flags> <worker cmd>`; the server binds a TCP listener, passes
# REPL_HOST/REPL_PORT/REPL_TOKEN/REPL_TRANSPORT via env, and validates the
# token in the worker's ready handshake (login nodes are shared machines — an
# open port is a code-injection risk). Transport: "direct" = worker connects
# to the login node's bound port; "tunnel" = worker runs `ssh -fN -L` on the
# compute node and connects through it.
"""Slurm launch helpers: launch_remote, tunnel_cmd, probe, config resolution."""
import json, os, secrets, shlex, shutil, socket, subprocess

_DEFAULT_TIMEOUT = 300
_runtime: dict = {}  # worker_mode tool overrides: {"mode", "flags", "transport"}


def set_runtime(mode=None, flags=None, transport=None):
    """Record worker_mode tool overrides. "" / None = no override (keep env)."""
    if mode is not None:
        _runtime["mode"] = mode
    if flags:
        _runtime["flags"] = flags
    if transport:
        _runtime["transport"] = transport


def reset_runtime():
    """Drop tool overrides (fresh server instance = env defaults again)."""
    _runtime.clear()


def slurm_enabled() -> bool:
    """True if sessions should launch via srun. A tool mode override beats env;
    mode="local" disables slurm even when INTERACTIVE_REPL_SLURM is set."""
    if "mode" in _runtime:
        return _runtime["mode"] == "slurm"
    return bool(os.environ.get("INTERACTIVE_REPL_SLURM"))


def flags() -> str:
    return _runtime.get("flags", os.environ.get("INTERACTIVE_REPL_SLURM", ""))


def transport() -> str:
    return _runtime.get("transport", os.environ.get("INTERACTIVE_REPL_TRANSPORT", "direct"))


def login_host() -> str:
    return os.environ.get("INTERACTIVE_REPL_HOST") or socket.gethostname()


def srun_timeout() -> int:
    try:
        return int(os.environ.get("INTERACTIVE_REPL_SRUN_TIMEOUT", _DEFAULT_TIMEOUT))
    except ValueError:
        return _DEFAULT_TIMEOUT


def new_token() -> str:
    return secrets.token_hex(16)


def srun_cmd(flags_str: str, cmd: list[str]) -> list[str]:
    return ["srun", *shlex.split(flags_str), *cmd]


def tunnel_cmd(local_port: int, login: str, remote_port: int) -> list[str]:
    """`ssh -fN -L <local>:localhost:<remote> <login>` — run on the COMPUTE node
    so connections to the compute node's localhost:<local> reach the server's
    listener on the login node. -f backgrounds after the tunnel is established,
    so the process exits 0 quickly on success; BatchMode forbids password
    prompts (jobs are non-interactive); ExitOnForwardFailure surfaces a bind
    collision as a non-zero exit."""
    return ["ssh", "-fN", "-L", f"{local_port}:localhost:{remote_port}", login,
            "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30", "-o", "ConnectTimeout=10"]


def probe() -> dict:
    """Environment detection for the worker_mode tool's decision logic."""
    return {
        "srun_available": shutil.which("srun") is not None,
        "already_in_allocation": bool(os.environ.get("SLURM_JOB_ID")),
        "ssh_available": shutil.which("ssh") is not None,
    }


def launch_remote(worker_cmd: list[str]) -> tuple:
    """srun-launch a worker and complete the callback handshake.

    Returns (proc, conn, meta) — conn is the accepted protocol socket, meta =
    {"transport", "job_id", "node"} (job info from the worker's ready message,
    which reads SLURM_JOB_ID / SLURM_JOB_NODELIST set by srun). Raises
    RuntimeError with a queue hint on accept timeout, or a token-mismatch error
    on handshake failure (possible unauthorized connection to the bound port)."""
    t = transport()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("0.0.0.0" if t == "direct" else "127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(srun_timeout())
    port = srv.getsockname()[1]
    token = new_token()
    env = {**os.environ, "REPL_PORT": str(port), "REPL_TOKEN": token,
           "REPL_HOST": login_host(), "REPL_TRANSPORT": t}
    proc = subprocess.Popen(srun_cmd(flags(), worker_cmd), env=env)
    try:
        conn, _ = srv.accept()
    except (socket.timeout, TimeoutError):
        try:
            proc.terminate()
        except Exception:
            pass
        raise RuntimeError(
            f"srun allocation did not start within {srun_timeout()}s — check "
            f"INTERACTIVE_REPL_SLURM flags and queue status (squeue). First "
            f"call blocks until the allocation starts.")
    finally:
        srv.close()
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = conn.recv(65536)
        if not chunk:
            proc.terminate()
            raise RuntimeError("worker exited before ready handshake (tunnel/ssh failure?)")
        buf += chunk
    ready = json.loads(buf.decode())
    if ready.get("token") != token:
        conn.close()
        proc.terminate()
        raise RuntimeError("token mismatch — possible unauthorized connection; session not created")
    if not ready.get("ready"):
        conn.close()
        proc.terminate()
        raise RuntimeError(f"worker failed to start: {ready!r}")
    meta = {"transport": t, "job_id": ready.get("job_id"), "node": ready.get("node")}
    return proc, conn, meta
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio python -m pytest tests/test_slurm.py -v`
Expected: PASS (14 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/altairwei/src/my-scientific-skills
git add data-science/interactive-repl/scripts/_slurm.py data-science/interactive-repl/tests/test_slurm.py
git commit -m "Add _slurm.py shared module: srun launch, token handshake, tunnel cmd, runtime config"
```

---

## Task 2: python worker TCP-client path (direct mode)

**Files:**
- Modify: `data-science/interactive-repl/scripts/python_worker.py` (`main()` protocol setup + ready message)
- Test: `data-science/interactive-repl/tests/test_python_worker.py` (append 1 test)

- [ ] **Step 1: Write the failing test (append to `tests/test_python_worker.py`)**

```python
import socket
import subprocess
import sys


def test_worker_tcp_mode_ready_and_roundtrip(monkeypatch, tmp_path):
    """Slurm mode: REPL_PORT set → worker speaks JSON-per-line over a TCP
    client socket; ready carries token + SLURM job info."""
    import pathlib
    worker = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "python_worker.py"
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    monkeypatch.setenv("REPL_PORT", str(port))
    monkeypatch.setenv("REPL_HOST", "127.0.0.1")
    monkeypatch.setenv("REPL_TOKEN", "tok123")
    monkeypatch.setenv("SLURM_JOB_ID", "999")
    monkeypatch.setenv("SLURM_JOB_NODELIST", "cn001")
    proc = subprocess.Popen([sys.executable, str(worker)], env=os.environ,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True)
    try:
        conn, _ = srv.accept()
        buf = b""
        while not buf.endswith(b"\n"):
            buf += conn.recv(65536)
        ready = json.loads(buf.decode())
        assert ready["ready"] is True
        assert ready["token"] == "tok123"
        assert ready["job_id"] == "999"
        assert ready["node"] == "cn001"
        conn.sendall(_encode_line({"id": "r1", "code": "1 + 1"}).encode())
        buf = b""
        while not buf.endswith(b"\n"):
            buf += conn.recv(65536)
        res = json.loads(buf.decode())
        assert res["id"] == "r1"
        assert res["error"] is None
        assert "2" in res["stdout"]
    finally:
        conn.close()
        proc.terminate()
        srv.close()
```

`_encode_line` already exists in `tests/test_python_worker.py` (it encodes `{"id","code"}` requests for the pipe protocol — the same line format works over the socket). Verify its name and signature when writing the test; adjust if it differs.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio python -m pytest tests/test_python_worker.py -k tcp -v`
Expected: FAIL — worker ignores `REPL_PORT` (pipes path only), so it never connects to the listener and `srv.accept()` blocks forever → test times out.

- [ ] **Step 3: Implement — TCP client path in `python_worker.py::main`**

Replace the current protocol-setup block (the two `os.fdopen(os.dup(...))` lines + the two `os.dup2(...devnull...)` lines at the top of `main()`) with:

```python
def main():
    # Protocol channel: TCP client when REPL_PORT is set (slurm/compute-node
    # mode, launched via srun), else stdin/stdout pipes (local mode). Real
    # stdin/stdout → devnull in both cases so user subprocesses inheriting
    # them can't corrupt the stream.
    port = os.environ.get("REPL_PORT")
    if port:
        import socket as _sock
        host = os.environ.get("REPL_HOST", "localhost")
        conn = _sock.create_connection((host, int(port)), timeout=30)
        protocol_in = conn.makefile("r", encoding="utf-8", errors="replace")
        protocol_out = conn.makefile("w", encoding="utf-8", buffering=1)
    else:
        protocol_in = os.fdopen(os.dup(0), "r", encoding="utf-8", errors="replace")
        protocol_out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
```

Then update the ready marker (the two lines `protocol_out.write(_common.encode_line({"ready": True}))` + `protocol_out.flush()`) to:

```python
    # Ready marker: token (validated by the server in slurm mode — an open
    # port on a shared login node is an injection risk) + SLURM job info.
    protocol_out.write(_common.encode_line({
        "ready": True,
        "token": os.environ.get("REPL_TOKEN", ""),
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "node": os.environ.get("SLURM_JOB_NODELIST"),
    }))
    protocol_out.flush()
```

- [ ] **Step 4: Run the new test + the existing worker tests**

Run: `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_worker.py -v`
Expected: PASS (13 tests: 12 existing + 1 new). Existing pipe-mode tests prove local mode is unchanged.

- [ ] **Step 5: Commit**

```bash
cd /home/altairwei/src/my-scientific-skills
git add data-science/interactive-repl/scripts/python_worker.py data-science/interactive-repl/tests/test_python_worker.py
git commit -m "python worker: TCP-client protocol path for slurm mode (REPL_PORT set), token in ready"
```

---

## Task 3: `repl.R` — REPL_HOST + token in ready

**Files:**
- Modify: `data-science/interactive-repl/scripts/repl.R` (connection host + ready message)
- Test: regression — the existing R server tests (`tests/test_r_server.py`) must stay green; the tunnel branch lands in Task 6

- [ ] **Step 1: Write the failing test — none new here; the red test for the R side is Task 6's tunnel integration. The regression bar: local-mode behavior is unchanged.**

Run the existing R tests first to confirm the baseline:
`cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic python -m pytest tests/test_r_server.py -v`
Expected: PASS (15 tests).

- [ ] **Step 2: Implement — `scripts/repl.R`**

Change the connection block (the `.repl$port` + `socketConnection(host = "localhost", ...)` lines) to:

```r
.repl$port <- as.integer(Sys.getenv("REPL_PORT", "0"))
if (is.na(.repl$port) || .repl$port <= 0) stop("REPL_PORT env var must be set to the server's TCP port")
# Slurm mode: REPL_HOST is the login node as seen from the compute node
# (default "localhost" = local mode). Direct transport connects straight
# across the interconnect; the tunnel branch (REPL_TRANSPORT=tunnel) is
# implemented in the same place — see the `if` below.
.repl$host <- Sys.getenv("REPL_HOST", "localhost")
.repl$con <- socketConnection(host = .repl$host, port = .repl$port, server = FALSE,
                              blocking = TRUE, open = "r+b", timeout = 86400L)
on.exit(close(.repl$con))
```

Change the ready marker (the `.repl$write_json(list(ready = TRUE))` line) to:

```r
# Ready marker: token (validated by the server in slurm mode) + SLURM job info.
.repl$write_json(list(ready = TRUE, token = Sys.getenv("REPL_TOKEN", ""),
                      job_id = Sys.getenv("SLURM_JOB_ID"),
                      node = Sys.getenv("SLURM_JOB_NODELIST")))
```

(Do NOT add the tunnel branch yet — Task 6 does that with its red test.)

- [ ] **Step 3: Run the R server tests to verify local mode is unchanged**

Run: `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic python -m pytest tests/test_r_server.py -v`
Expected: PASS (15 tests). The extra ready keys are ignored by the local-mode server (it only checks `ready`).

- [ ] **Step 4: Commit**

```bash
cd /home/altairwei/src/my-scientific-skills
git add data-science/interactive-repl/scripts/repl.R
git commit -m "repl.R: REPL_HOST env for remote connections, token + SLURM job info in ready"
```

---

## Task 4: python server slurm branch + fake-srun integration test

**Files:**
- Modify: `data-science/interactive-repl/scripts/python_repl_server.py` (`_Session` struct, `_start`/`_send`/`_recv`/`_call_worker`/`restart`/`session_info` + `SessionInfo` model)
- Test: `data-science/interactive-repl/tests/test_slurm.py` (append the shim fixtures + python integration tests)

- [ ] **Step 1: Write the failing tests (append to `tests/test_slurm.py`)**

First the shim helpers and fixtures:

```python
import pathlib
import textwrap

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"

FAKE_SRUN = textwrap.dedent("""\
    #!/bin/sh
    echo "srun $*" >> "$FAKE_SRUN_LOG"
    export SLURM_JOB_ID=4242
    export SLURM_JOB_NODELIST=cn042
    exec "$@"
    """)

FAKE_SCANCEL = textwrap.dedent("""\
    #!/bin/sh
    echo "scancel $*" >> "$FAKE_SCANCEL_LOG"
    exit 0
    """)


def _install_shims(tmp_path, monkeypatch, names=("srun", "scancel")):
    """Write fake srun/scancel shims to tmp_path, put them on PATH, and point
    their log env vars at log files. srun records argv, injects SLURM_* env,
    and execs the real worker command; scancel records its args."""
    for name in names:
        body = FAKE_SRUN if name == "srun" else FAKE_SCANCEL
        shim = tmp_path / name
        shim.write_text(body)
        shim.chmod(0o755)
        monkeypatch.setenv(f"FAKE_{name.upper()}_LOG", str(tmp_path / f"{name}.log"))
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
```

Then the python-server integration tests (append):

```python
@pytest.mark.asyncio
async def test_slurm_python_end_to_end(monkeypatch, tmp_path):
    """INTERACTIVE_REPL_SLURM set + fake srun on PATH → sessions launch via
    srun, worker connects back, session_info reports the SLURM job."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=test -c 4")
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")  # loopback in tests
    _install_shims(tmp_path, monkeypatch)
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "slp1", "code": "1 + 1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]
        si = (await client.call_tool("session_info", {"session": "slp1"})).structured_content
        assert si["job_id"] == "4242"
        assert si["node"] == "cn042"
        assert si["transport"] == "direct"
        assert si["running"] is True
        log = (tmp_path / "srun.log").read_text()
        assert "--partition=test -c 4" in log


@pytest.mark.asyncio
async def test_slurm_python_restart_scancels(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "-c 4")
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")
    _install_shims(tmp_path, monkeypatch)
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "slp2", "code": "x = 1"})
        r = await client.call_tool("restart", {"session": "slp2"})
        assert r.structured_content["ok"] is True
        assert "4242" in (tmp_path / "scancel.log").read_text()
        # session restarted: namespace wiped, new session works
        r2 = await client.call_tool("run_code", {"session": "slp2", "code": "x"})
        assert r2.structured_content["error"] is not None  # NameError after restart


@pytest.mark.asyncio
async def test_slurm_python_token_mismatch_rejected(monkeypatch, tmp_path):
    """A worker that returns the wrong token must be refused (shared login
    node: an open port is an injection risk)."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "-c 4")
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")
    _install_shims(tmp_path, monkeypatch)
    wrong = tmp_path / "srun"
    wrong.write_text(FAKE_SRUN + "\nexport REPL_TOKEN=wrongtoken\n")
    wrong.chmod(0o755)
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "slp3", "code": "1"})
        assert r.isError
        assert "token mismatch" in str(r.content)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic python -m pytest tests/test_slurm.py -k slurm_python -v`
Expected: FAIL — the python server has no slurm branch: sessions start locally, so `session_info.job_id` is `None` (`!= "4242"`), the `srun.log` never appears, and `scancel` is never invoked.

- [ ] **Step 3: Implement — `scripts/python_repl_server.py`**

a) Import `_slurm` next to the other shared imports (after `import _chunk_parser`):

```python
import _slurm  # noqa: E402
```

b) Add a session struct after `_sessions` (replacing `_sessions: dict[str, subprocess.Popen] = {}`):

```python
class _Session:
    """One worker. Local mode: proc pipes carry the protocol. Slurm mode:
    conn is the accepted TCP socket; job_id/node/transport come from the
    worker's ready handshake (SLURM_JOB_ID / SLURM_JOB_NODELIST)."""

    def __init__(self, proc, conn=None, job_id=None, node=None, transport="local"):
        self.proc = proc
        self.conn = conn
        self.job_id = job_id
        self.node = node
        self.transport = transport


_sessions: dict[str, _Session] = {}
```

c) Add `_send`/`_recv` helpers above `_start`:

```python
def _send(s: _Session, line: str) -> None:
    if s.conn is not None:
        s.conn.sendall(line.encode())
    else:
        s.proc.stdin.write(line)
        s.proc.stdin.flush()


def _recv(s: _Session) -> str:
    if s.conn is not None:
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.conn.recv(65536)
            if not chunk:
                raise OSError("connection closed")
            buf += chunk
        return buf.decode()
    line = s.proc.stdout.readline()
    if not line:
        raise OSError("pipe closed")
    return line
```

d) Replace `_start` (lines 116-131) and `_get` (134-139):

```python
def _start(session: str) -> _Session:
    if _slurm.slurm_enabled():
        proc, conn, meta = _slurm.launch_remote([sys.executable, str(WORKER)])
        s = _Session(proc, conn, meta["job_id"], meta["node"], meta["transport"])
    else:
        p = subprocess.Popen(
            [sys.executable, str(WORKER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )
        ready = json.loads(p.stdout.readline())
        if not ready.get("ready"):
            raise RuntimeError(f"worker failed to start: {ready!r} {p.stderr.read()!r}")
        s = _Session(p)
    # Auto-inject the base sidecar so _peek/_who/_fig are available immediately.
    base = _base_sidecar_src()
    if base:
        _send(s, _common.encode_line({"id": "init", "code": base}))
        _recv(s)  # discard the init response
    return s


def _get(session: str) -> _Session:
    s = _sessions.get(session)
    if s is None or s.proc.poll() is not None:
        s = _start(session)
        _sessions[session] = s
    return s
```

e) Replace `_call_worker` (142-157) to route over `_send`/`_recv`:

```python
def _call_worker(session: str, code: str) -> dict:
    s = _get(session)
    rid = uuid.uuid4().hex
    try:
        _send(s, _common.encode_line({"id": rid, "code": code}))
        line = _recv(s)
    except (BrokenPipeError, OSError) as e:
        _sessions.pop(session, None)
        return {"stdout": "", "stderr": "", "error": f"worker died: {e}",
                "plots": [], "truncated": False, "degraded": False}
    return _common.decode_line(line)
```

f) Extend the `SessionInfo` model and `session_info` tool:

```python
class SessionInfo(BaseModel):
    session: str
    running: bool
    pid: int | None = None
    plot_dir: str = ""
    job_id: str | None = None
    node: str | None = None
    transport: str = "local"
```

```python
@mcp.tool()
def session_info(session: str) -> SessionInfo:
    """Report whether the named session is running, its pid, the plot dir, and
    (slurm mode) the compute-node job id / node / transport."""
    s = _sessions.get(session)
    running = s is not None and s.proc.poll() is None
    return SessionInfo(session=session, running=running,
                       pid=s.proc.pid if running else None,
                       plot_dir=_common.plot_dir(),
                       job_id=s.job_id if running else None,
                       node=s.node if running else None,
                       transport=s.transport if running else None)
```

g) Update `restart` to scancel + resubmit in slurm mode:

```python
@mcp.tool()
def restart(session: str) -> Ack:
    """Kill and respawn the named session's worker — wipes the namespace.
    In slurm mode this scancels the allocation and resubmits under the
    current worker mode. Use after a worker crash or to deliberately reset
    state. Loses DB connections and loaded data, so use sparingly."""
    s = _sessions.pop(session, None)
    if s is not None:
        if s.job_id:
            try:
                subprocess.run(["scancel", s.job_id], timeout=10, capture_output=True)
            except Exception:
                pass
        try:
            if s.conn is not None:
                s.conn.close()
            else:
                s.proc.stdin.close()
        except Exception:
            pass
        try:
            s.proc.terminate(); s.proc.wait(timeout=2)
        except Exception:
            pass
    return Ack(ok=True, message=f"restarted session '{session}'")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic python -m pytest tests/test_slurm.py -k slurm_python -v`
Expected: PASS (3 tests). Then run the full python server suite (regression — local mode untouched):
`uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_server.py tests/test_python_worker.py -v`
Expected: PASS (28 tests: 15 + 13).

- [ ] **Step 5: Commit**

```bash
cd /home/altairwei/src/my-scientific-skills
git add data-science/interactive-repl/scripts/python_repl_server.py data-science/interactive-repl/tests/test_slurm.py
git commit -m "python-repl server: srun launch branch, scancel restart, session_info job/node/transport"
```

---

## Task 5: R server slurm branch + fake-srun integration test

**Files:**
- Modify: `data-science/interactive-repl/scripts/r_repl_server.py` (`_Session` fields, `_start`, `restart`, `session_info` + `SessionInfo` model)
- Test: `data-science/interactive-repl/tests/test_slurm.py` (append R integration tests)

- [ ] **Step 1: Write the failing tests (append to `tests/test_slurm.py`)**

```python
@pytest.mark.asyncio
async def test_slurm_r_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=test -c 4")
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")
    _install_shims(tmp_path, monkeypatch)
    from mcp import Client
    from r_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "slr1", "code": "1 + 1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]
        si = (await client.call_tool("session_info", {"session": "slr1"})).structured_content
        assert si["job_id"] == "4242"
        assert si["node"] == "cn042"
        assert si["transport"] == "direct"
        assert "srun" in (tmp_path / "srun.log").read_text()


@pytest.mark.asyncio
async def test_slurm_r_restart_scancels(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "-c 4")
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")
    _install_shims(tmp_path, monkeypatch)
    from mcp import Client
    from r_repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "slr2", "code": "x <- 1"})
        r = await client.call_tool("restart", {"session": "slr2"})
        assert r.structured_content["ok"] is True
        assert "4242" in (tmp_path / "scancel.log").read_text()
        r2 = await client.call_tool("run_code", {"session": "slr2", "code": "x"})
        assert r2.structured_content["error"] is not None  # object not found after restart
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic python -m pytest tests/test_slurm.py -k slurm_r -v`
Expected: FAIL — R server ignores slurm mode (starts locally), `session_info.job_id` is `None`.

- [ ] **Step 3: Implement — `scripts/r_repl_server.py`**

a) Import `_slurm` next to `import _chunk_parser`:

```python
import _slurm  # noqa: E402
```

b) Extend `_Session` (lines 25-28):

```python
class _Session:
    def __init__(self, proc, conn, job_id=None, node=None, transport="local"):
        self.proc = proc
        self.conn = conn
        self.job_id = job_id
        self.node = node
        self.transport = transport
```

c) Extend `SessionInfo` (lines 94-98) with the three new optional fields:

```python
class SessionInfo(BaseModel):
    session: str
    running: bool
    pid: int | None = None
    plot_dir: str = ""
    job_id: str | None = None
    node: str | None = None
    transport: str = "local"
```

d) Branch `_start` (lines 119-148). Keep the local path exactly as-is; wrap it in the `else` and add the slurm branch before it:

```python
def _start(session: str) -> _Session:
    r_env = os.environ.get("INTERACTIVE_REPL_R_ENV")
    r_bin = os.environ.get("INTERACTIVE_REPL_R_BIN", "R")
    argv = [r_bin, "--no-save", "--no-restore", "-f", str(REPL_R)]
    cmd = (["conda", "run", "-n", r_env, "--no-capture-output", *argv]
           if r_env else argv)
    if _slurm.slurm_enabled():
        proc, conn, meta = _slurm.launch_remote(cmd)
        s = _Session(proc, conn, meta["job_id"], meta["node"], meta["transport"])
    else:
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        srv.settimeout(30)
        port = srv.getsockname()[1]
        env = {**os.environ, "REPL_PORT": str(port)}
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        conn, _ = srv.accept()
        srv.close()  # accepted conn is independent of the listener
        buf = b""
        while not buf.endswith(b"\n"):
            buf += conn.recv(65536)
        ready = json.loads(buf.decode())
        if not ready.get("ready"):
            raise RuntimeError(f"R worker failed to start: {ready!r} {proc.stderr.read()!r}")
        s = _Session(proc, conn)
    # Auto-source the base sidecar so who/peek/fig are available immediately.
    base = _base_sidecar_src()
    if base:
        conn.sendall(_common.encode_line({"id": "init", "code": base}).encode())
        buf = b""
        while not buf.endswith(b"\n"):
            buf += conn.recv(65536)
    return s
```

(Note: the slurm branch returns with `conn` already valid and the ready line already consumed by `launch_remote`; the sidecar inject below runs for both branches — exactly the existing behavior.)

e) Update `restart` (lines 297-306) to scancel in slurm mode:

```python
    s = _sessions.pop(session, None)
    if s is not None:
        if s.job_id:
            try:
                subprocess.run(["scancel", s.job_id], timeout=10, capture_output=True)
            except Exception:
                pass
        try: s.conn.close()
        except Exception: pass
        try: s.proc.terminate(); s.proc.wait(timeout=2)
        except Exception: pass
```

f) Update `session_info` (lines 310-315):

```python
    s = _sessions.get(session)
    running = s is not None and s.proc.poll() is None
    return SessionInfo(session=session, running=running,
                       pid=s.proc.pid if running else None,
                       plot_dir=_common.plot_dir(),
                       job_id=s.job_id if running else None,
                       node=s.node if running else None,
                       transport=s.transport if running else None)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic python -m pytest tests/test_slurm.py -k slurm_r tests/test_r_server.py -v`
Expected: PASS (17 tests: 2 new + 15 regression).

- [ ] **Step 5: Commit**

```bash
cd /home/altairwei/src/my-scientific-skills
git add data-science/interactive-repl/scripts/r_repl_server.py data-science/interactive-repl/tests/test_slurm.py
git commit -m "r-repl server: srun launch branch, scancel restart, session_info job/node/transport"
```

---

## Task 6: tunnel transport — wiring + fake-ssh integration tests

**Files:**
- Modify: `data-science/interactive-repl/scripts/python_worker.py` (tunnel branch in the TCP path)
- Modify: `data-science/interactive-repl/scripts/repl.R` (tunnel branch before the direct connection)
- Test: `data-science/interactive-repl/tests/test_slurm.py` (fake-ssh shim + 2 integration tests)

- [ ] **Step 1: Write the failing tests (append to `tests/test_slurm.py`)**

The fake ssh shim emulates `ssh -fN -L L:localhost:P host`: it forks a proxy that listens on the compute-side port L and forwards to localhost:P, then the parent exits 0 (exactly what `-f` does — the worker uses the exit status as the tunnel-ready check).

```python
FAKE_SSH = textwrap.dedent("""\
    #!/usr/bin/env python3
    # Fake `ssh` for tests: emulate `-fN -L L:localhost:P host` by forking a
    # proxy (listen on L, forward to localhost:P) and exiting 0. The child
    # exits when the single proxied connection closes.
    import os, socket, select, sys

    args = sys.argv[1:]
    local = remote = None
    for i, a in enumerate(args):
        if a == "-L":
            spec = args[i + 1]  # "L:localhost:P"
            local = int(spec.split(":")[0])
            remote = int(spec.split(":")[2])

    def proxy():
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", local))
        srv.listen(1)
        conn, _ = srv.accept()          # the worker's connection
        up = socket.create_connection(("127.0.0.1", remote), timeout=10)
        conn.setblocking(False)
        up.setblocking(False)
        while True:
            r, _, _ = select.select([conn, up], [], [], 1.0)
            if not r:
                continue
            for src in r:
                dst = up if src is conn else conn
                try:
                    data = src.recv(65536)
                except BlockingIOError:
                    continue
                if not data:
                    return
                dst.sendall(data)

    if os.fork() == 0:                  # child keeps proxying
        try:
            proxy()
        finally:
            os._exit(0)
    os._exit(0)                         # parent: tunnel "up", exit 0
    """)
```

(Note: no `#!/bin/sh` here — python3 may be `python3` or `python` on PATH; the shim is invoked by the worker's `ssh` lookup. If `python3` is missing on the test machine, use `sys.executable` from the worker... For robustness the shim shebang is `#!/usr/bin/env python3` — standard on Linux.)

And the tests:

```python
@pytest.mark.asyncio
async def test_tunnel_python_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "-c 4")
    monkeypatch.setenv("INTERACTIVE_REPL_TRANSPORT", "tunnel")
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")
    _install_shims(tmp_path, monkeypatch, names=("srun", "scancel", "ssh"))
    (tmp_path / "ssh").write_text(FAKE_SSH)
    (tmp_path / "ssh").chmod(0o755)
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "tun1", "code": "1 + 1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]
        si = (await client.call_tool("session_info", {"session": "tun1"})).structured_content
        assert si["transport"] == "tunnel"
        assert si["job_id"] == "4242"


@pytest.mark.asyncio
async def test_tunnel_r_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "-c 4")
    monkeypatch.setenv("INTERACTIVE_REPL_TRANSPORT", "tunnel")
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")
    _install_shims(tmp_path, monkeypatch, names=("srun", "scancel", "ssh"))
    (tmp_path / "ssh").write_text(FAKE_SSH)
    (tmp_path / "ssh").chmod(0o755)
    from mcp import Client
    from r_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "tun2", "code": "1 + 1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]
        si = (await client.call_tool("session_info", {"session": "tun2"})).structured_content
        assert si["transport"] == "tunnel"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic python -m pytest tests/test_slurm.py -k tunnel -v`
Expected: FAIL — no tunnel wiring yet:
- python worker: `REPL_TRANSPORT=tunnel` env is ignored → direct connect to `REPL_HOST:REPL_PORT`... wait, in the test the server binds `127.0.0.1` for tunnel transport, and the worker (Task 2 code) connects to `REPL_HOST` (=127.0.0.1) at `REPL_PORT` directly — the listener IS on 127.0.0.1:P, so the direct connect would accidentally succeed! Both transports collapse. That means the test must distinguish: assert the ssh shim was actually invoked (its absence from the flow is the real red). Fix the test: check that the fake ssh shim's proxy ran. Add to both tests:

```python
        # the tunnel must actually be used: the fake ssh proxy created a
        # listener — verify by checking the srun log shows the ssh invocation
        log = (tmp_path / "srun.log").read_text()
        assert "ssh" in log
```

Hmm — `srun.log` records the srun argv: `srun -c 4 <python> <worker>` — no ssh there. The ssh invocation happens INSIDE the worker, not via srun. So instead: assert the shim's `-L` was exercised by checking... the fake ssh writes nothing. Make the fake ssh log its argv: add `import os; os.environ.get("FAKE_SSH_LOG")` and append `" ".join(sys.argv)` to it before forking. Then the test asserts `"ssh" in (tmp_path / "ssh.log").read_text()`.

Update FAKE_SSH: at the top, before the loop:

```python
import os, socket, select, sys
_log = os.environ.get("FAKE_SSH_LOG")
if _log:
    with open(_log, "a") as f:
        f.write("ssh " + " ".join(sys.argv[1:]) + "\n")
```

And `_install_shims(..., names=("srun", "scancel", "ssh"))` already sets `FAKE_SSH_LOG`. Then the red assertion for both tunnel tests:

```python
        assert "-L" in (tmp_path / "ssh.log").read_text()   # tunnel actually used
```

Without wiring, `ssh.log` never appears → FAIL. With wiring, it does. This is a genuine red→green. Include this assertion in the final test code above (replace the vague comment with the real assertion).

- [ ] **Step 3: Implement — tunnel wiring**

a) `scripts/python_worker.py` — replace the `port:` branch's direct `create_connection` with a tunnel-aware version (use `_slurm.tunnel_cmd` — DRY, it's the same dir and pure stdlib):

```python
    port = os.environ.get("REPL_PORT")
    if port:
        import socket as _sock
        import _slurm
        host = os.environ.get("REPL_HOST", "localhost")
        if os.environ.get("REPL_TRANSPORT") == "tunnel":
            # ssh -fN -L <L>:localhost:<port> forwards the server's listener
            # to this node; pick a free local port first. The foreground ssh
            # exits 0 once the tunnel is up (check=True) — non-zero means
            # bind collision / auth failure → fail fast.
            s = _sock.socket()
            s.bind(("127.0.0.1", 0))
            local_port = s.getsockname()[1]
            s.close()
            subprocess.run(_slurm.tunnel_cmd(local_port, host, int(port)),
                           check=True, timeout=30)
            conn = _sock.create_connection(("127.0.0.1", local_port), timeout=30)
        else:
            conn = _sock.create_connection((host, int(port)), timeout=30)
        protocol_in = conn.makefile("r", encoding="utf-8", errors="replace")
        protocol_out = conn.makefile("w", encoding="utf-8", buffering=1)
    else:
        protocol_in = os.fdopen(os.dup(0), "r", encoding="utf-8", errors="replace")
        protocol_out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)
```

b) `scripts/repl.R` — replace the connection block (from Task 3) with the tunnel branch:

```r
.repl$host <- Sys.getenv("REPL_HOST", "localhost")
.repl$con <- NULL
if (identical(Sys.getenv("REPL_TRANSPORT"), "tunnel")) {
  # Tunnel mode: ssh -fN -L <L>:localhost:<port> <host> forwards the server's
  # listener to this (compute) node. Base R cannot read an OS-assigned
  # port=0, so probe a random high port; system2(wait=TRUE) returns the ssh
  # exit status — with -f the foreground exits quickly either way, so 0 means
  # the tunnel is up (bind collision / auth failure → non-zero → retry).
  for (i in 1:5) {
    L <- 20000 + sample(20000, 1)
    probe <- tryCatch({
      c <- socketConnection(host = "localhost", port = L, server = TRUE,
                            open = "r+b", timeout = 5)
      close(c)
      TRUE
    }, error = function(e) FALSE)
    if (!probe) next
    st <- system2("ssh", c("-fN", "-L", sprintf("%d:localhost:%d", L, .repl$port),
                           .repl$host, "-o", "BatchMode=yes",
                           "-o", "ExitOnForwardFailure=yes",
                           "-o", "ServerAliveInterval=30",
                           "-o", "ConnectTimeout=10"), wait = TRUE)
    if (st != 0) next
    .repl$con <- socketConnection(host = "localhost", port = L, server = FALSE,
                                  blocking = TRUE, open = "r+b", timeout = 86400L)
    break
  }
  if (is.null(.repl$con)) {
    stop("ssh -L tunnel to ", .repl$host, " failed (check passwordless ssh)")
  }
} else {
  .repl$con <- socketConnection(host = .repl$host, port = .repl$port, server = FALSE,
                                blocking = TRUE, open = "r+b", timeout = 86400L)
}
on.exit(close(.repl$con))
```

(The `.repl$port` guard from Task 3 stays above this block.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic python -m pytest tests/test_slurm.py -k tunnel -v`
Expected: PASS (2 tests) — the worker's `ssh -fN -L` invocation goes through the fake shim, and `ssh.log` shows `-L`.

- [ ] **Step 5: Commit**

```bash
cd /home/altairwei/src/my-scientific-skills
git add data-science/interactive-repl/scripts/python_worker.py data-science/interactive-repl/scripts/repl.R data-science/interactive-repl/tests/test_slurm.py
git commit -m "Tunnel transport: ssh -fN -L wiring in both workers + fake-ssh end-to-end tests"
```

---

## Task 7: `worker_mode` tool (both servers)

**Files:**
- Modify: `data-science/interactive-repl/scripts/python_repl_server.py` (WorkerModeInfo/Probe models + tool)
- Modify: `data-science/interactive-repl/scripts/r_repl_server.py` (same)
- Test: `data-science/interactive-repl/tests/test_slurm.py` (append 4 tests)

- [ ] **Step 1: Write the failing tests (append to `tests/test_slurm.py`)**

```python
@pytest.mark.asyncio
async def test_worker_mode_probe_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.delenv("INTERACTIVE_REPL_SLURM", raising=False)
    monkeypatch.delenv("INTERACTIVE_REPL_TRANSPORT", raising=False)
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("worker_mode", {})
        sc = r.structured_content
        assert sc["mode"] == "local"
        assert sc["source"] == "env"
        assert sc["transport"] == "direct"
        assert set(sc["probe"]) == {"srun_available", "already_in_allocation", "ssh_available"}


@pytest.mark.asyncio
async def test_worker_mode_switch_routes_new_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")
    _install_shims(tmp_path, monkeypatch)
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("worker_mode", {"mode": "slurm", "slurm_flags": "--partition=test"})
        sc = r.structured_content
        assert sc["mode"] == "slurm"
        assert sc["source"] == "tool"
        assert sc["slurm_flags"] == "--partition=test"
        # new session goes through srun
        await client.call_tool("run_code", {"session": "wm1", "code": "1 + 1"})
        si = (await client.call_tool("session_info", {"session": "wm1"})).structured_content
        assert si["job_id"] == "4242"
        assert "--partition=test" in (tmp_path / "srun.log").read_text()


@pytest.mark.asyncio
async def test_worker_mode_local_overrides_env(monkeypatch, tmp_path):
    """Tool mode=local beats INTERACTIVE_REPL_SLURM set in the environment."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=env")
    _install_shims(tmp_path, monkeypatch)
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("worker_mode", {"mode": "local"})
        assert r.structured_content["mode"] == "local"
        await client.call_tool("run_code", {"session": "wm2", "code": "1 + 1"})
        si = (await client.call_tool("session_info", {"session": "wm2"})).structured_content
        assert si["transport"] == "local"
        assert not (tmp_path / "srun.log").exists()   # no srun was launched


@pytest.mark.asyncio
async def test_worker_mode_switch_does_not_affect_existing_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")
    _install_shims(tmp_path, monkeypatch)
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("worker_mode", {"mode": "slurm"})
        await client.call_tool("run_code", {"session": "wm3", "code": "x = 42"})
        # switch to local — the running session must keep working
        await client.call_tool("worker_mode", {"mode": "local"})
        r = await client.call_tool("run_code", {"session": "wm3", "code": "x"})
        assert "42" in r.structured_content["stdout"]
        si = (await client.call_tool("session_info", {"session": "wm3"})).structured_content
        assert si["transport"] == "direct"      # launched under slurm, still slurm
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic python -m pytest tests/test_slurm.py -k worker_mode -v`
Expected: FAIL — `worker_mode` tool doesn't exist → unknown tool error from the client.

- [ ] **Step 3: Implement — add the models + tool to BOTH servers (identical code, following the existing per-server model duplication pattern)**

Add before `@mcp.tool()` definitions (after the `Ack` model in each server):

```python
class Probe(BaseModel):
    srun_available: bool = False
    already_in_allocation: bool = False
    ssh_available: bool = False


class WorkerModeInfo(BaseModel):
    mode: str
    source: str
    slurm_flags: str = ""
    transport: str = "direct"
    host: str = ""
    timeout: int = 300
    probe: Probe
```

Add the tool (place next to `session_info`):

```python
@mcp.tool()
def worker_mode(mode: str = None, slurm_flags: str = None,
                transport: str = None) -> WorkerModeInfo:
    """Get or set how this server launches workers. No args = probe the
    environment (srun present? already inside a job? ssh for tunnels?) and
    report the current mode and its source ("env" default or "tool" override).
    mode="local"|"slurm" switches; slurm_flags overrides
    INTERACTIVE_REPL_SLURM (omit or pass "" to keep the env default);
    transport="direct"|"tunnel" overrides INTERACTIVE_REPL_TRANSPORT. Tool
    settings apply to sessions created after the switch (existing sessions
    keep running until restart) and reset when the server restarts."""
    if mode is not None:
        _slurm.set_runtime(mode=mode)
    if slurm_flags is not None:
        _slurm.set_runtime(flags=slurm_flags)
    if transport is not None:
        _slurm.set_runtime(transport=transport)
    return WorkerModeInfo(
        mode="slurm" if _slurm.slurm_enabled() else "local",
        source="tool" if "mode" in _slurm._runtime else "env",
        slurm_flags=_slurm.flags(),
        transport=_slurm.transport(),
        host=_slurm.login_host(),
        timeout=_slurm.srun_timeout(),
        probe=Probe(**_slurm.probe()),
    )
```

(`_slurm._runtime` is intentionally read directly — it is the same module instance the server imports, so the source check is honest.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic python -m pytest tests/test_slurm.py -k worker_mode -v`
Expected: PASS (4 tests, python server). The R server gets the same tool — add a smoke test for it:

```python
@pytest.mark.asyncio
async def test_worker_mode_r_server_smoke(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from r_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("worker_mode", {})
        sc = r.structured_content
        assert sc["mode"] == "local"
        assert set(sc["probe"]) == {"srun_available", "already_in_allocation", "ssh_available"}
```

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic python -m pytest tests/test_slurm.py -k worker_mode -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
cd /home/altairwei/src/my-scientific-skills
git add data-science/interactive-repl/scripts/python_repl_server.py data-science/interactive-repl/scripts/r_repl_server.py data-science/interactive-repl/tests/test_slurm.py
git commit -m "worker_mode tool on both servers: probe + runtime switch (local/slurm, flags, transport)"
```

---

## Task 8: Documentation

**Files:**
- Create: `data-science/interactive-repl/references/slurm-hpc.md`
- Modify: `data-science/interactive-repl/SKILL.md`
- Modify: `data-science/interactive-repl/references/troubleshooting.md`
- Modify: `README.md` (repo root)

- [ ] **Step 1: Create `references/slurm-hpc.md`**

```markdown
# HPC / Slurm — run REPL workers on compute nodes

At HPC centers, login nodes must not run long or compute-heavy work — compute
belongs on a compute node allocated via `srun`. This skill can launch each REPL
worker inside an srun allocation and talk to it across the network. Off by
default; activate via `worker_mode()` (runtime) or `INTERACTIVE_REPL_SLURM`
(persistent).

## When to use

- The task is heavy (big joins, training, simulations) and the host is a login node.
- The user mentions 超算/集群/slurm/srun/sbatch/队列/配额/partition.
- `worker_mode()` reports `probe.srun_available: true` and the task is heavy.

## Decision flow — call `worker_mode()` with no args first

1. `probe.srun_available: false` → stay `local`; tell the user this host has no Slurm.
2. `probe.already_in_allocation: true` → stay `local` — Claude Code is already
   running inside a job; a nested srun allocation is pointless.
3. Otherwise, for heavy work → `worker_mode(mode="slurm")`. Flags: use the
   user's partition/account/cpus/mem if they told you, else pass nothing
   (keeps the env default).
4. Session over / task turned light → `worker_mode(mode="local")` to stop
   submitting jobs.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `INTERACTIVE_REPL_SLURM` | unset | srun flags, e.g. `--partition=compute --account=acct -c 16 --mem=64G`. Non-empty → all sessions of this server launch via srun. |
| `INTERACTIVE_REPL_TRANSPORT` | `direct` | `direct` (worker connects to the login node) or `tunnel` (worker runs `ssh -fN -L` back to the login node). |
| `INTERACTIVE_REPL_HOST` | `hostname` | Login-node hostname as seen from compute nodes; also the tunnel's ssh target. |
| `INTERACTIVE_REPL_SRUN_TIMEOUT` | `300` | Max queue wait + startup (seconds). |

`worker_mode()` overrides all of these at runtime (per server process); tool
settings beat env vars, apply to sessions created after the switch, and reset
when the server restarts.

## Prerequisites — read before using

1. **`CLAUDE_PLUGIN_DATA` must point at shared storage.** The default
   `/tmp/interactive-repl-data` is per-node: plots saved on a compute node
   would be invisible on the login node, and the lazy-install `py-site` would
   be built twice. Export it to a shared path (e.g. under your home) before
   using slurm mode.
2. Login and compute nodes share home (standard on HPC) — this is what makes
   the worker scripts, the uv-managed python, R/conda envs, `uv`, and ssh keys
   available on the compute node.
3. Direct transport: compute nodes must reach the login node's TCP ports. If
   not, set `INTERACTIVE_REPL_TRANSPORT=tunnel` — the worker then needs
   passwordless ssh from the compute node to the login node (shared home
   usually provides it).

## Semantics

- **First call blocks**: `run_code` auto-creates the session, which submits
  the srun job and waits for the allocation (`INTERACTIVE_REPL_SRUN_TIMEOUT`).
  Queue wait is real — tell the user the session is queued.
- **Allocation expiry ≈ data loss.** srun's `-t` bounds the session. When the
  allocation ends the connection drops — `run_code` returns `worker died`;
  `restart(session)` resubmits (a fresh namespace). Size `-t` for the work.
- **`restart`** scancels the old job and resubmits under the current mode.
- **`session_info`** reports `job_id` / `node` / `transport` — tell the user
  where the session runs ("on cn042, job 74213").
- **Switching modes** only affects new sessions; existing sessions keep
  running until restarted.
- **Security**: slurm sessions carry a token handshake, so other users of the
  shared login node cannot inject code into the bound port.

## Common failures

- `srun allocation did not start within 300s` — flags wrong (bad
  partition/account) or queue busy; check `squeue`, fix flags, retry.
- `worker died` mid-session — allocation expired or was preempted → `restart`.
- Tunnel mode fails at session start — ssh from the compute node to the login
  node must be passwordless; check `~/.ssh` keys on the shared home.
- Plots not readable after slurm sessions — `CLAUDE_PLUGIN_DATA` is not on
  shared storage (see Prerequisites).

## Escape hatch

Run the entire Claude Code inside `srun --pty` — everything stays localhost
and zero configuration is needed. Use it when the whole session belongs on a
compute node; use slurm mode when you work on the login node and compute on
nodes.
```

- [ ] **Step 2: Update `SKILL.md`**

a) Add the `worker_mode` bullet to the tools list, right after the `session_info` bullet (line 53):

```markdown
- `worker_mode(mode?, slurm_flags?, transport?)` — probe or switch how workers launch: `local` (default) vs `slurm` (srun on a compute node). Call it with no args to detect the environment; switch for HPC work. See `references/slurm-hpc.md`.
```

b) Add an HPC section after "## When to restart (rarely)" (after line 82):

```markdown
## HPC / Slurm — compute nodes

On supercomputing clusters, heavy compute must run on a compute node, not the
login node. `worker_mode()` on the server probes the environment
(`srun_available`, `already_in_allocation`, `ssh_available`) and switches
between `local` and `slurm` launch — call it before heavy work when the user
mentions clusters/queues/partitions. Slurm sessions are tied to the
allocation: expiry surfaces as `worker died` → `restart` resubmits (fresh
namespace). Requires shared storage for plots (`CLAUDE_PLUGIN_DATA`) — see
`references/slurm-hpc.md`.
```

c) Add `references/slurm-hpc.md` to the "Deep docs" list (after the
`references/notebook-iteration.md` entry):

```markdown
`references/slurm-hpc.md` (HPC: run workers on compute nodes via srun),
```

- [ ] **Step 3: Update `references/troubleshooting.md` — append a section at the end**

```markdown
## Slurm / HPC

- `srun allocation did not start within Ns` — flags wrong (bad partition/account)
  or the queue is busy. Check `squeue`, fix `INTERACTIVE_REPL_SLURM`, retry.
- `worker died` after a slurm session started — the allocation expired or was
  preempted; `restart(session)` resubmits (fresh namespace — re-run the setup).
- Tunnel mode fails at session start — ssh from the compute node to the login
  node must be passwordless (`ssh login-node` with no prompt).
- Plots from a compute-node session are missing — `CLAUDE_PLUGIN_DATA` points
  at per-node storage; export it to shared storage (see `slurm-hpc.md`).
```

- [ ] **Step 4: Update `README.md`**

a) Extend the `interactive-repl` row in the data-science table (line 24) — append:

```
; HPC/Slurm compute-node sessions
```

b) In the MCP paragraph (line 81), extend the last sentence:

```
It is Claude-Code-specific; the other skills remain tool-agnostic and portable
across agent platforms. Its workers can also run on Slurm compute nodes
(srun + callback transport) for HPC centers.
```

- [ ] **Step 5: Verify size limits and run the full suite**

Run: `cd /home/altairwei/src/my-scientific-skills && ./count-skill-tokens.py data-science/interactive-repl`
Expected: SKILL.md under 500 lines / 5,000 tokens; description under 100 tokens.

Run (full suite): `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/ -v`
Expected: PASS — 93 existing + 28 new = **121 tests**.

- [ ] **Step 6: Commit**

```bash
cd /home/altairwei/src/my-scientific-skills
git add data-science/interactive-repl/references/slurm-hpc.md data-science/interactive-repl/SKILL.md data-science/interactive-repl/references/troubleshooting.md README.md
git commit -m "Docs: HPC/Slurm reference, worker_mode in SKILL.md, troubleshooting + README entries"
```

---

## Self-Review

**1. Spec coverage** — every spec requirement maps to a task:
- §Architecture `_slurm.py` (launch_remote/srun_cmd/new_token/login_host/srun_timeout/tunnel_cmd/probe/flags/transport) → Task 1.
- §python_worker TCP-client path (direct) + ready token/job/node → Task 2; tunnel branch → Task 6.
- §repl.R REPL_HOST + ready token → Task 3; tunnel branch → Task 6.
- §servers _start/restart (scancel)/session_info (job_id/node/transport) python → Task 4, R → Task 5.
- §worker_mode tool (probe, switch, precedence, new-sessions-only, reset-on-restart) → Task 7.
- §testing (worker TCP unit, fake srun/scancel/ssh shims, tunnel e2e, worker_mode, local regression) → Tasks 2, 4, 5, 6, 7.
- §docs (slurm-hpc.md, SKILL.md, troubleshooting.md, README.md) → Task 8.
- §out-of-scope items are absent from all tasks (no sbatch, no per-session mode, no PBS).

**2. Placeholder scan** — no TBD/TODO; every code step shows complete code. The one conditional in Task 2 Step 1 (`_encode_line` name check) is a verification instruction, not a placeholder. The `if a == "-fN" or a == "-f": daemonize = True` fragment was dropped in favor of always-fork (see Task 6 Step 2 note) — the final shim always daemonizes.

**3. Type consistency** — `launch_remote` returns `(proc, conn, meta)` with `meta = {transport, job_id, node}`; Tasks 4/5 destructure the same three keys. `_Session(proc, conn, job_id, node, transport)` signature identical in both servers; `SessionInfo` gains the same three optional fields in both. `_slurm.set_runtime(mode=.../flags=.../transport=...)` matches the worker_mode tool's three params; `flags()`/`transport()`/`login_host()`/`srun_timeout()`/`probe()` used by `WorkerModeInfo` fields match the spec's JSON example. Test session names are unique per test (`slp1..3`, `slr1..2`, `tun1..2`, `wm1..3`) — no cross-test state bleed within a server process.

**4. One deliberate divergence from the naive spec:** Task 6 Step 2 catches that in tunnel mode the server binds `127.0.0.1:P` and the naive worker would *directly* connect to `REPL_HOST:REPL_PORT` — which, when `REPL_HOST=127.0.0.1` (as tests set), accidentally succeeds and silently skips the tunnel. The fix is the `ssh.log` assertion (`-L` present) making the tunnel's actual use a tested fact. Real-world deployments don't have this collision (REPL_HOST is the login node's real hostname), but the test locks the wiring in regardless.

No further issues. Plan is complete.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-07-slurm-repl.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
