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


# ---------------------------------------------------------------------------
# Slurm integration tests — fake srun / scancel / ssh shims on a temp PATH
# ---------------------------------------------------------------------------

import textwrap

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"

FAKE_SRUN = textwrap.dedent("""\
    #!/bin/sh
    # Real srun consumes its own flags and runs the remaining argv as the job
    # command. Strip flags by position: the worker command always starts with
    # an absolute path (python / Rscript / conda run ...) or a bare `R`.
    # Flag parsing can't know srun's per-flag arity, so stop at the first
    # arg that is a path or R/conda — that's the command.
    echo "srun $*" >> "$FAKE_SRUN_LOG"
    while [ $# -gt 0 ]; do
      case "$1" in
        */*) break ;;
        R|conda) break ;;
        *) shift ;;
      esac
    done
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


@pytest.mark.asyncio
async def test_slurm_python_end_to_end(monkeypatch, tmp_path):
    """INTERACTIVE_REPL_SLURM set + fake srun on PATH → sessions launch via
    srun, worker connects back, session_info reports the SLURM job."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=test -c 4")
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")  # loopback in tests
    _install_shims(tmp_path, monkeypatch)
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "py:slp1", "code": "1 + 1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]
        si = (await client.call_tool("session_info", {"session": "py:slp1"})).structured_content
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
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:slp2", "code": "x = 1"})
        r = await client.call_tool("restart", {"session": "py:slp2"})
        assert r.structured_content["ok"] is True
        assert "4242" in (tmp_path / "scancel.log").read_text()
        # session restarted: namespace wiped, new session works
        r2 = await client.call_tool("run_code", {"session": "py:slp2", "code": "x"})
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
    # inject the wrong token before the FINAL exec "$@" line so it reaches the
    # worker (a line appended after exec would be dead code). rsplit targets
    # only the last occurrence — str.replace would also mangle the backtick
    # comment in FAKE_SRUN and break the shim's shell syntax.
    head, _, _ = FAKE_SRUN.rpartition('exec "$@"')
    wrong.write_text(head + 'export REPL_TOKEN=wrongtoken\nexec "$@"\n')
    wrong.chmod(0o755)
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        # session-start failures are structured errors, not tool-level failures
        r = await client.call_tool("run_code", {"session": "py:slp3", "code": "1"})
        sc = r.structured_content
        assert sc["error"] is not None
        assert "token mismatch" in sc["error"]


@pytest.mark.asyncio
async def test_slurm_r_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=test -c 4")
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")
    _install_shims(tmp_path, monkeypatch)
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "r:slr1", "code": "1 + 1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]
        si = (await client.call_tool("session_info", {"session": "r:slr1"})).structured_content
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
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "r:slr2", "code": "x <- 1"})
        r = await client.call_tool("restart", {"session": "r:slr2"})
        assert r.structured_content["ok"] is True
        assert "4242" in (tmp_path / "scancel.log").read_text()
        r2 = await client.call_tool("run_code", {"session": "r:slr2", "code": "x"})
        assert r2.structured_content["error"] is not None  # object not found after restart


FAKE_SSH = textwrap.dedent("""\
    #!/usr/bin/env python3
    # Fake `ssh` for tests: emulate `-fN -L L:localhost:P host` by forking a
    # proxy (listen on L, forward to localhost:P) and exiting 0. The child
    # exits when the single proxied connection closes.
    import os, socket, select, sys

    _log = os.environ.get("FAKE_SSH_LOG")
    if _log:
        with open(_log, "a") as f:
            f.write("ssh " + " ".join(sys.argv[1:]) + "\\n")

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
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "py:tun1", "code": "1 + 1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]
        si = (await client.call_tool("session_info", {"session": "py:tun1"})).structured_content
        assert si["transport"] == "tunnel"
        assert si["job_id"] == "4242"
        # the tunnel must actually be used — the naive worker would connect
        # directly to 127.0.0.1:<port> and silently skip the ssh forwarding
        assert "-L" in (tmp_path / "ssh.log").read_text()


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
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "r:tun2", "code": "1 + 1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]
        si = (await client.call_tool("session_info", {"session": "r:tun2"})).structured_content
        assert si["transport"] == "tunnel"
        assert "-L" in (tmp_path / "ssh.log").read_text()


@pytest.mark.asyncio
async def test_worker_mode_probe_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.delenv("INTERACTIVE_REPL_SLURM", raising=False)
    monkeypatch.delenv("INTERACTIVE_REPL_TRANSPORT", raising=False)
    from mcp import Client
    from repl_server import mcp
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
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("worker_mode", {"mode": "slurm", "slurm_flags": "--partition=test"})
        sc = r.structured_content
        assert sc["mode"] == "slurm"
        assert sc["source"] == "tool"
        assert sc["slurm_flags"] == "--partition=test"
        # new session goes through srun
        await client.call_tool("run_code", {"session": "py:wm1", "code": "1 + 1"})
        si = (await client.call_tool("session_info", {"session": "py:wm1"})).structured_content
        assert si["job_id"] == "4242"
        assert "--partition=test" in (tmp_path / "srun.log").read_text()


@pytest.mark.asyncio
async def test_worker_mode_local_overrides_env(monkeypatch, tmp_path):
    """Tool mode=local beats INTERACTIVE_REPL_SLURM set in the environment."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=env")
    _install_shims(tmp_path, monkeypatch)
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("worker_mode", {"mode": "local"})
        assert r.structured_content["mode"] == "local"
        await client.call_tool("run_code", {"session": "py:wm2", "code": "1 + 1"})
        si = (await client.call_tool("session_info", {"session": "py:wm2"})).structured_content
        assert si["transport"] == "local"
        assert not (tmp_path / "srun.log").exists()   # no srun was launched


@pytest.mark.asyncio
async def test_worker_mode_switch_does_not_affect_existing_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")
    _install_shims(tmp_path, monkeypatch)
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("worker_mode", {"mode": "slurm"})
        await client.call_tool("run_code", {"session": "py:wm3", "code": "x = 42"})
        # switch to local — the running session must keep working
        await client.call_tool("worker_mode", {"mode": "local"})
        r = await client.call_tool("run_code", {"session": "py:wm3", "code": "x"})
        assert "42" in r.structured_content["stdout"]
        si = (await client.call_tool("session_info", {"session": "py:wm3"})).structured_content
        assert si["transport"] == "direct"      # launched under slurm, still slurm


@pytest.mark.asyncio
async def test_worker_mode_r_server_smoke(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("worker_mode", {})
        sc = r.structured_content
        assert sc["mode"] == "local"
        assert set(sc["probe"]) == {"srun_available", "already_in_allocation", "ssh_available"}
