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


class VarSummary(BaseModel):
    name: str
    type: str
    size: str = ""
    preview: str = ""
    has_children: bool = False


class VarList(BaseModel):
    variables: list[VarSummary]


class InspectResult(BaseModel):
    name: str
    repr: str
    error: str | None = None


# Code injected into the worker to list session variables as JSON.
# Defines a tiny _sz helper (underscore-prefixed → filtered from its own listing),
# then prints a JSON list of {name,type,size,preview,has_children} for non-underscore
# globals. exec semantics (no auto-print) → explicit print().
_LIST_VARS_CODE = (
    "import json as _j\n"
    "def _sz(v):\n"
    "    try:\n"
    "        return str(len(v))\n"
    "    except Exception:\n"
    "        return ''\n"
    "print(_j.dumps([{'name': n, 'type': type(v).__name__, 'size': _sz(v), "
    "'preview': repr(v)[:120], "
    "'has_children': hasattr(v, '__len__') and not isinstance(v, (str, bytes))} "
    "for n, v in sorted(globals().items()) if not n.startswith('_')]))"
)


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


@mcp.tool()
def list_variables(session: str) -> VarList:
    """List variables in the session namespace with type/size/preview summaries."""
    r = _call_worker(session, _LIST_VARS_CODE)
    if r.get("error"):
        return VarList(variables=[])
    try:
        parsed = json.loads(r["stdout"].strip().split("\n")[-1])
        return VarList(variables=[VarSummary(**v) for v in parsed])
    except Exception:
        return VarList(variables=[])


@mcp.tool()
def inspect_variable(session: str, name: str, path: list = None) -> InspectResult:
    """Inspect a variable's repr, optionally drilling by path (e.g. ['df','col'])."""
    expr = name
    if path:
        for p in path:
            expr += f"[{p!r}]"
    r = _call_worker(session, f"print(repr({expr}))")
    return InspectResult(name=name, repr=r.get("stdout", ""), error=r.get("error"))


@mcp.tool()
def inject(session: str, path: str) -> Ack:
    """Exec a kernel.py sidecar into the session namespace — the extensibility
    mechanism for other skills. The sidecar should be top-level definitions only
    (lazy imports), no side-effect code at load."""
    with open(path, "r") as f:
        code = f.read()
    r = _call_worker(session, code)
    return Ack(ok=r.get("error") is None, message=r.get("error") or f"injected {path}")


if __name__ == "__main__":
    mcp.run()
