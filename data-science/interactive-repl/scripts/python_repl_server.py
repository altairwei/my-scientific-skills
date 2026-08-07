#!/usr/bin/env python3
# data-science/interactive-repl/scripts/python_repl_server.py
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp", "pydantic"]
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
import _chunk_parser  # noqa: E402
import _slurm  # noqa: E402

mcp = MCPServer("python-repl")


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


class RunResult(BaseModel):
    stdout: str
    stderr: str
    error: str | None = None
    plots: list[str] = Field(default_factory=list)
    truncated: bool = False
    degraded: bool = False


class ChunkRan(BaseModel):
    index: int
    label: str
    language: str


class ChunkSkipped(BaseModel):
    index: int
    label: str
    language: str
    reason: str


class RunChunkResult(BaseModel):
    stdout: str
    stderr: str
    error: str | None = None
    plots: list[str] = Field(default_factory=list)
    truncated: bool = False
    degraded: bool = False
    ran: list[ChunkRan] = Field(default_factory=list)
    skipped: list[ChunkSkipped] = Field(default_factory=list)
    failed_chunk: ChunkRan | None = None


_LANG = "python"


class SessionInfo(BaseModel):
    session: str
    running: bool
    pid: int | None = None
    plot_dir: str = ""
    job_id: str | None = None
    node: str | None = None
    transport: str = "local"


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
    "for n, v in sorted(globals().items()) "
    "if not n.startswith('_') and n not in {'json','math','os','re','sys'}]))"
)


def _base_sidecar_src() -> str:
    """The base kernel.py sidecar (peek/who/fig) — auto-injected at session start."""
    p = HERE / "kernel.py"
    return p.read_text() if p.exists() else ""


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


def _call_worker(session: str, code: str) -> dict:
    rid = uuid.uuid4().hex
    try:
        s = _get(session)
        _send(s, _common.encode_line({"id": rid, "code": code}))
        line = _recv(s)
    except (BrokenPipeError, OSError) as e:
        _sessions.pop(session, None)
        return {"stdout": "", "stderr": "", "error": f"worker died: {e}",
                "plots": [], "truncated": False, "degraded": False}
    except RuntimeError as e:
        # session-start failures (queue timeout, token mismatch, worker refused
        # to start) surface as structured errors — raising here hangs the MCP
        # request in the in-process client (exceptions are not auto-converted).
        _sessions.pop(session, None)
        return {"stdout": "", "stderr": "", "error": str(e),
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
def run_chunk(session: str, file: str, selector: str) -> RunChunkResult:
    """Run one chunk (or a range) from a .Rmd/.qmd/.ipynb notebook in the session.
    selector = label | index | 'N-M' | 'N-'. Parses, resolves, runs each chunk in
    notebook order via the session worker. Skips eval=FALSE and wrong-language chunks
    (listed in `skipped`). Stops on first error (dependency order). Pass an absolute
    `file` path — the server's cwd may differ from the agent's."""
    try:
        chunks = _chunk_parser.parse_notebook(file)
    except (FileNotFoundError, ValueError) as e:
        return RunChunkResult(stdout="", stderr="", error=str(e))
    try:
        selected = _chunk_parser.resolve_selector(chunks, selector)
    except ValueError as e:
        return RunChunkResult(stdout="", stderr="", error=str(e))

    # Set the session cwd to the notebook's dir so relative paths in chunks resolve
    # (pd.read_csv("data.csv"), open("helper.py") — relative to the notebook, not the
    # server's launch dir).
    nb_dir = str(Path(file).resolve().parent)
    r = _call_worker(session, f"import os; os.chdir({nb_dir!r})")
    if r.get("error"):
        return RunChunkResult(stdout="", stderr="", error=f"os.chdir({nb_dir}) failed: {r['error']}")

    ran: list[ChunkRan] = []
    skipped: list[ChunkSkipped] = []
    out_parts: list[str] = []
    err_parts: list[str] = []
    plots: list[str] = []
    truncated = False
    degraded = False
    for c in selected:
        if not c.eval:
            skipped.append(ChunkSkipped(index=c.index, label=c.label,
                                        language=c.language, reason="eval=FALSE"))
            continue
        if c.language != _LANG:
            other = "r-repl" if _LANG == "python" else "python-repl"
            skipped.append(ChunkSkipped(index=c.index, label=c.label, language=c.language,
                                        reason=f"language={c.language}, use {other}"))
            continue
        r = _call_worker(session, c.code)
        if r.get("error"):
            return RunChunkResult(
                stdout="\n".join(s for s in out_parts if s),
                stderr="\n".join(s for s in err_parts if s),
                error=r["error"], plots=plots, truncated=truncated, degraded=degraded,
                ran=ran, skipped=skipped,
                failed_chunk=ChunkRan(index=c.index, label=c.label, language=c.language))
        out_parts.append(r.get("stdout", ""))
        err_parts.append(r.get("stderr", ""))
        plots.extend(r.get("plots") or [])
        truncated = truncated or r.get("truncated", False)
        degraded = degraded or r.get("degraded", False)
        ran.append(ChunkRan(index=c.index, label=c.label, language=c.language))
    return RunChunkResult(
        stdout="\n".join(s for s in out_parts if s),
        stderr="\n".join(s for s in err_parts if s),
        error=None, plots=plots, truncated=truncated, degraded=degraded,
        ran=ran, skipped=skipped, failed_chunk=None)


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
