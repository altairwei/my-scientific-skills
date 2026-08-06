#!/usr/bin/env python3
# data-science/interactive-repl/scripts/python_repl_server.py
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp", "pydantic", "numpy", "matplotlib", "pandas"]
# ///
"""python-repl MCP stdio server. Spawns python_worker.py per named session
and proxies tool calls to it over JSON-per-line stdin/stdout."""
import json, subprocess, sys, uuid
from pathlib import Path
from pydantic import BaseModel, Field
from mcp.server import MCPServer

HERE = Path(__file__).resolve().parent
WORKER = HERE / "python_worker.py"
sys.path.insert(0, str(HERE))
import _common  # noqa: E402

mcp = MCPServer("python-repl")
_sessions: dict[str, subprocess.Popen] = {}


class RunResult(BaseModel):
    stdout: str
    stderr: str
    error: str | None = None
    plots: list[str] = Field(default_factory=list)
    truncated: bool = False
    degraded: bool = False


class SessionInfo(BaseModel):
    session: str
    running: bool
    pid: int | None = None
    plot_dir: str = ""


class Ack(BaseModel):
    ok: bool
    message: str = ""


def _start(session: str) -> subprocess.Popen:
    p = subprocess.Popen(
        [sys.executable, str(WORKER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    ready = json.loads(p.stdout.readline())
    if not ready.get("ready"):
        raise RuntimeError(f"worker failed to start: {ready!r} {p.stderr.read()!r}")
    return p


def _get(session: str) -> subprocess.Popen:
    p = _sessions.get(session)
    if p is None or p.poll() is not None:
        p = _start(session)
        _sessions[session] = p
    return p


def _call_worker(session: str, code: str) -> dict:
    p = _get(session)
    rid = uuid.uuid4().hex
    try:
        p.stdin.write(_common.encode_line({"id": rid, "code": code}))
        p.stdin.flush()
        line = p.stdout.readline()
    except (BrokenPipeError, OSError) as e:
        _sessions.pop(session, None)
        return {"stdout": "", "stderr": "", "error": f"worker died: {e}",
                "plots": [], "truncated": False, "degraded": False}
    if not line:
        _sessions.pop(session, None)
        return {"stdout": "", "stderr": "", "error": "worker died (no output)",
                "plots": [], "truncated": False, "degraded": False}
    return _common.decode_line(line)


def _to_run_result(r: dict) -> RunResult:
    return RunResult(
        stdout=r.get("stdout", ""),
        stderr=r.get("stderr", ""),
        error=r.get("error"),
        plots=r.get("plots") or [],
        truncated=r.get("truncated", False),
        degraded=r.get("degraded", False),
    )


@mcp.tool()
def run_code(session: str, code: str, timeout: int = 300) -> RunResult:
    """Execute Python code in a persistent REPL session. Variables, imports, and
    loaded data persist across calls. Returns stdout, stderr, error (traceback or
    None), plots (saved-PNG paths), and truncated/degraded flags. The session is
    auto-created on first call. Use distinct session names per task.

    The `timeout` parameter is advisory in v1 — the worker blocks until the code
    returns; a stuck cell surfaces as a worker-died error (call `restart`)."""
    return _to_run_result(_call_worker(session, code))


@mcp.tool()
def session_info(session: str) -> SessionInfo:
    """Report whether the named session is running, its pid, and the plot dir."""
    p = _sessions.get(session)
    running = p is not None and p.poll() is None
    return SessionInfo(session=session, running=running,
                       pid=p.pid if running else None, plot_dir=_common.plot_dir())


@mcp.tool()
def restart(session: str) -> Ack:
    """Kill and respawn the named session's worker — wipes the namespace.
    Use after a worker crash or to deliberately reset state. Loses DB
    connections and loaded data, so use sparingly."""
    p = _sessions.pop(session, None)
    if p is not None:
        try:
            p.stdin.close()
        except Exception:
            pass
        try:
            p.terminate(); p.wait(timeout=2)
        except Exception:
            pass
    return Ack(ok=True, message=f"restarted session '{session}'")


if __name__ == "__main__":
    mcp.run()
