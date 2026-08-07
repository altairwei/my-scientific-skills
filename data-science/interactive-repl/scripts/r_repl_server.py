#!/usr/bin/env python3
# data-science/interactive-repl/scripts/r_repl_server.py
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp", "pydantic"]
# ///
"""r-repl MCP stdio server. Spawns an R worker (repl.R) per named session and
proxies tool calls to it over a TCP localhost socket (R base socketConnection is
TCP-only — no Unix domain sockets — so the server binds 127.0.0.1:0 and passes
the ephemeral port to R via REPL_PORT)."""
import json, os, socket, subprocess, sys, uuid
from pathlib import Path
from pydantic import BaseModel, Field
from mcp.server import MCPServer

HERE = Path(__file__).resolve().parent
REPL_R = HERE / "repl.R"
sys.path.insert(0, str(HERE))
import _common  # noqa: E402
import _chunk_parser  # noqa: E402

mcp = MCPServer("r-repl")


class _Session:
    def __init__(self, proc, conn):
        self.proc = proc
        self.conn = conn


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


_LANG = "r"


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


class Ack(BaseModel):
    ok: bool
    message: str = ""


class SessionInfo(BaseModel):
    session: str
    running: bool
    pid: int | None = None
    plot_dir: str = ""


# R code injected to list .GlobalEnv objects as JSON. lapply + jsonlite::toJSON.
_LIST_VARS_R = (
    "objs <- lapply(ls(envir=.GlobalEnv), function(nm) {"
    "  o <- get(nm, envir=.GlobalEnv); dm <- dim(o);"
    "  list(name=nm, type=class(o)[1],"
    "       size=if(is.null(dm)) as.character(length(o)) else paste(dm, collapse='x'),"
    "       preview='',"
    "       has_children=is.recursive(o) && length(o) > 0)"
    "}); cat(jsonlite::toJSON(objs, auto_unbox=TRUE, null='null'))"
)


def _base_sidecar_src() -> str:
    """The base kernel.R sidecar (who/peek/fig) — auto-sourced at session start."""
    p = HERE / "kernel.R"
    return p.read_text() if p.exists() else ""


def _start(session: str) -> _Session:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(30)
    port = srv.getsockname()[1]
    r_env = os.environ.get("INTERACTIVE_REPL_R_ENV")
    r_bin = os.environ.get("INTERACTIVE_REPL_R_BIN", "R")
    argv = [r_bin, "--no-save", "--no-restore", "-f", str(REPL_R)]
    env = {**os.environ, "REPL_PORT": str(port)}
    cmd = (["conda", "run", "-n", r_env, "--no-capture-output", *argv]
           if r_env else argv)
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
    # Auto-source the base sidecar so who/peek/fig are available immediately.
    base = _base_sidecar_src()
    if base:
        conn.sendall(_common.encode_line({"id": "init", "code": base}).encode())
        buf = b""
        while not buf.endswith(b"\n"):
            buf += conn.recv(65536)
    return _Session(proc, conn)


def _get(session: str) -> _Session:
    s = _sessions.get(session)
    if s is None or s.proc.poll() is not None:
        s = _start(session)
        _sessions[session] = s
    return s


def _call_worker(session: str, code: str) -> dict:
    s = _get(session)
    rid = uuid.uuid4().hex
    try:
        s.conn.sendall(_common.encode_line({"id": rid, "code": code}).encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.conn.recv(65536)
            if not chunk:
                _sessions.pop(session, None)
                return {"stdout": "", "stderr": "", "error": "R worker died (no output)",
                        "plots": [], "truncated": False, "degraded": False}
            buf += chunk
        return _common.decode_line(buf.decode())
    except (BrokenPipeError, OSError) as e:
        _sessions.pop(session, None)
        return {"stdout": "", "stderr": "", "error": f"R worker died: {e}",
                "plots": [], "truncated": False, "degraded": False}


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
    """Execute R code in a persistent REPL session. Variables, libraries, and
    loaded data persist across calls. Returns stdout, stderr, error, plots
    (saved-PNG paths), truncated/degraded. The session is auto-created on first
    call. Use distinct session names per task."""
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
    # (source("helper.R"), read.csv("data.csv") — r-cell's `cd analysis/phenotypes` lesson).
    nb_dir = str(Path(file).resolve().parent)
    r = _call_worker(session, f"setwd({nb_dir!r})")
    if r.get("error"):
        return RunChunkResult(stdout="", stderr="", error=f"setwd({nb_dir}) failed: {r['error']}")

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
def list_variables(session: str) -> VarList:
    """List R objects in .GlobalEnv with class/size/preview summaries."""
    r = _call_worker(session, _LIST_VARS_R)
    if r.get("error"):
        return VarList(variables=[])
    try:
        parsed = json.loads(r["stdout"].strip().split("\n")[-1])
        return VarList(variables=[VarSummary(**v) for v in parsed])
    except Exception:
        return VarList(variables=[])


@mcp.tool()
def inspect_variable(session: str, name: str, path: list = None) -> InspectResult:
    """Inspect an R object's str + head (optionally drilling by path)."""
    expr = name
    if path:
        for p in path:
            expr += f"[[{p!r}]]"
    code = f"print(str({expr})); print(utils::head({expr}, 10))"
    r = _call_worker(session, code)
    return InspectResult(name=name, repr=r.get("stdout", ""), error=r.get("error"))


@mcp.tool()
def inject(session: str, path: str) -> Ack:
    """Source an R sidecar (kernel.R) into the session namespace — the
    extensibility mechanism for other skills. The sidecar should be top-level
    definitions only, lazy deps."""
    with open(path, "r") as f:
        code = f.read()
    r = _call_worker(session, code)
    return Ack(ok=r.get("error") is None, message=r.get("error") or f"injected {path}")


@mcp.tool()
def restart(session: str) -> Ack:
    """Kill + respawn the R worker — wipes .GlobalEnv. Use sparingly (loses
    DB connections and loaded data)."""
    s = _sessions.pop(session, None)
    if s is not None:
        try: s.conn.close()
        except Exception: pass
        try: s.proc.terminate(); s.proc.wait(timeout=2)
        except Exception: pass
    return Ack(ok=True, message=f"restarted R session '{session}'")


@mcp.tool()
def session_info(session: str) -> SessionInfo:
    """Report whether the named R session is running, its pid, and the plot dir."""
    s = _sessions.get(session)
    running = s is not None and s.proc.poll() is None
    return SessionInfo(session=session, running=running,
                       pid=s.proc.pid if running else None, plot_dir=_common.plot_dir())


if __name__ == "__main__":
    mcp.run()
