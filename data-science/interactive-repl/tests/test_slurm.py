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
    # command — strip leading srun flags (attached or space-separated values)
    # so `exec "$@"` runs just the worker command.
    echo "srun $*" >> "$FAKE_SRUN_LOG"
    while [ $# -gt 0 ]; do
      case "$1" in
        -*)
          shift
          if [ $# -gt 0 ]; then
            case "$1" in
              -*) ;;
              *) shift ;;
            esac
          fi
          ;;
        *) break ;;
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
    # inject the wrong token before the FINAL exec "$@" line so it reaches the
    # worker (a line appended after exec would be dead code). rsplit targets
    # only the last occurrence — str.replace would also mangle the backtick
    # comment in FAKE_SRUN and break the shim's shell syntax.
    head, _, _ = FAKE_SRUN.rpartition('exec "$@"')
    wrong.write_text(head + 'export REPL_TOKEN=wrongtoken\nexec "$@"\n')
    wrong.chmod(0o755)
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        # session-start failures are structured errors, not tool-level failures
        r = await client.call_tool("run_code", {"session": "slp3", "code": "1"})
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
    from python_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "tun1", "code": "1 + 1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]
        si = (await client.call_tool("session_info", {"session": "tun1"})).structured_content
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
    from r_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "tun2", "code": "1 + 1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]
        si = (await client.call_tool("session_info", {"session": "tun2"})).structured_content
        assert si["transport"] == "tunnel"
        assert "-L" in (tmp_path / "ssh.log").read_text()
