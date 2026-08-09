import os
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


def test_srun_timeout_default_and_parse(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_REPL_SRUN_TIMEOUT", raising=False)
    assert _slurm.srun_timeout() == 300
    monkeypatch.setenv("INTERACTIVE_REPL_SRUN_TIMEOUT", "600")
    assert _slurm.srun_timeout() == 600
    monkeypatch.setenv("INTERACTIVE_REPL_SRUN_TIMEOUT", "abc")
    assert _slurm.srun_timeout() == 300


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


@pytest.mark.asyncio
async def test_slurm_python_end_to_end(monkeypatch, tmp_path):
    """INTERACTIVE_REPL_SLURM set + fake srun on PATH → sessions launch via
    srun, worker connects back, session_info reports the SLURM job."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=test -c 4")
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
        assert si["running"] is True
        log = (tmp_path / "srun.log").read_text()
        assert "--partition=test -c 4" in log
        assert "--partition=test -c 4" in (tmp_path / "salloc.log").read_text()


@pytest.mark.asyncio
async def test_slurm_python_restart_scancels(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "-c 4")
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
async def test_slurm_python_close_scancels(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "-c 4")
    _install_shims(tmp_path, monkeypatch)
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:slc1", "code": "x = 1"})
        r = await client.call_tool("close", {"session": "py:slc1"})
        assert r.structured_content["ok"] is True
        assert "4242" in (tmp_path / "scancel.log").read_text()
        si = (await client.call_tool("session_info", {"session": "py:slc1"})).structured_content
        assert si["running"] is False
        # a fresh run_code on the same name starts a new allocation
        r2 = await client.call_tool("run_code", {"session": "py:slc1", "code": "x"})
        assert r2.structured_content["error"] is not None  # NameError after close


@pytest.mark.asyncio
async def test_slurm_r_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=test -c 4")
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
        assert "srun" in (tmp_path / "srun.log").read_text()


@pytest.mark.asyncio
async def test_slurm_r_restart_scancels(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "-c 4")
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


@pytest.mark.asyncio
async def test_worker_mode_probe_defaults(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.delenv("INTERACTIVE_REPL_SLURM", raising=False)
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("worker_mode", {})
        sc = r.structured_content
        assert sc["mode"] == "local"
        assert sc["source"] == "env"
        assert set(sc["probe"]) == {"srun_available", "already_in_allocation"}


@pytest.mark.asyncio
async def test_worker_mode_switch_routes_new_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
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
        assert not (tmp_path / "srun.log").exists()   # no srun was launched


@pytest.mark.asyncio
async def test_worker_mode_switch_does_not_affect_existing_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
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


@pytest.mark.asyncio
async def test_worker_mode_r_server_smoke(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("worker_mode", {})
        sc = r.structured_content
        assert sc["mode"] == "local"
        assert set(sc["probe"]) == {"srun_available", "already_in_allocation"}
