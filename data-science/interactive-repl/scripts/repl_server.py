#!/usr/bin/env python3
# data-science/interactive-repl/scripts/repl_server.py
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp", "pydantic"]
# ///
"""repl MCP stdio server. One server for both languages: the language lives in
the session name — 'r:<name>' spawns an R worker (repl.R), 'py:<name>' spawns
python_worker.py. Language-specific bits live in _LANGUAGES; everything else
is shared glue (session pool, proxying, capping, slurm)."""
import json, os, selectors, subprocess, sys, time, uuid
from pathlib import Path
from pydantic import BaseModel, Field
from mcp.server import MCPServer

HERE = Path(__file__).resolve().parent
WORKER = HERE / "python_worker.py"
REPL_R = HERE / "repl.R"
sys.path.insert(0, str(HERE))
import _common  # noqa: E402
import _chunk_parser  # noqa: E402
import _slurm  # noqa: E402

mcp = MCPServer("repl")


class _Session:
    """One worker. Local mode: proc pipes carry the protocol. Slurm mode:
    the same pipes are forwarded by the salloc/srun chain; job_id/node come
    from the worker's ready handshake (SLURM_JOB_ID / SLURM_JOB_NODELIST)."""

    def __init__(self, proc, job_id=None, node=None):
        self.proc = proc
        self.job_id = job_id
        self.node = node


_sessions: dict[str, _Session] = {}


def _parse_session(name: str):
    """'r:lmp' -> ('r', 'lmp'); 'py:lmp' -> ('py', 'lmp'); anything else -> None."""
    if ":" in name:
        lang, _, bare = name.partition(":")
        bare = bare.strip()  # "r: " -> None; "r:  lmp " -> ("r", "lmp")
        if lang in _LANGUAGE_PREFIXES and bare:
            return lang, bare
    return None


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


class SessionInfo(BaseModel):
    session: str
    running: bool
    pid: int | None = None
    plot_dir: str = ""
    job_id: str | None = None
    node: str | None = None
    error: str | None = None


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
    error: str | None = None


class InspectResult(BaseModel):
    name: str
    repr: str
    error: str | None = None


class Probe(BaseModel):
    srun_available: bool = False
    already_in_allocation: bool = False


class WorkerModeInfo(BaseModel):
    mode: str
    source: str
    slurm_flags: str = ""
    timeout: int = 300
    probe: Probe


# Code injected into the worker to list session variables as JSON.
# Defines a tiny _sz helper (underscore-prefixed → filtered from its own listing),
# then prints a JSON list of {name,type,size,preview,has_children} for non-underscore
# globals. exec semantics (no auto-print) → explicit print().
_LIST_VARS_PY = (
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


def _py_worker_cmd() -> list:
    """The py worker's interpreter: INTERACTIVE_REPL_PY_BIN (a project's
    conda-env python) or the server's own interpreter."""
    py_bin = os.environ.get("INTERACTIVE_REPL_PY_BIN")
    return [py_bin or sys.executable, str(WORKER)]


def _r_worker_cmd() -> list:
    r_env = os.environ.get("INTERACTIVE_REPL_R_ENV")
    r_bin = os.environ.get("INTERACTIVE_REPL_R_BIN", "R")
    argv = [r_bin, "--quiet", "--no-echo", "--no-save", "--no-restore", "-f", str(REPL_R)]
    return (["conda", "run", "-n", r_env, "--no-capture-output", *argv]
            if r_env else argv)


# The language-specific core, keyed by session-name prefix. Everything else in
# this file is shared glue (session pool, proxying, capping, slurm).
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

# Valid session-name prefixes are exactly the registry keys — a language that
# isn't in _LANGUAGES yet parses as None and surfaces the structured ambiguity
# error instead of a KeyError.
_LANGUAGE_PREFIXES = set(_LANGUAGES)


def _base_sidecar_src(lang: str) -> str:
    """The base sidecar (kernel.py / kernel.R) — auto-injected at session start."""
    p = HERE / _LANGUAGES[lang]["sidecar"]
    return p.read_text() if p.exists() else ""


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


def _get(lang: str, bare: str) -> _Session:
    key = f"{lang}:{bare}"
    s = _sessions.get(key)
    if s is None or s.proc.poll() is not None:
        s = _start(lang, bare)
        _sessions[key] = s
    return s


_AMBIG = "ambiguous session name — use 'r:<name>' or 'py:<name>'"


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
    """Execute code in a persistent REPL session — R or Python. The session
    name carries the language: 'r:<name>' for R, 'py:<name>' for Python
    (auto-created on first call). Variables, imports, and loaded data persist
    across calls. Returns stdout, stderr, error (traceback or condition), plots
    (saved-PNG paths), and truncated/degraded flags.

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
    parsed = _parse_session(session)
    if parsed is None:
        return RunChunkResult(stdout="", stderr="", error=_AMBIG)
    lang, _ = parsed
    if lang == "py":
        lang = "python"  # chunk parser's language vocabulary is 'r' | 'python'
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
    if lang == "python":
        r = _call_worker(session, f"import os; os.chdir({nb_dir!r})")
    elif lang == "r":
        r = _call_worker(session, f"setwd({nb_dir!r})")
    else:
        return RunChunkResult(stdout="", stderr="", error=f"no cwd handling for language {lang!r}")
    if r.get("error"):
        cwd_call = "os.chdir" if lang == "python" else "setwd"
        return RunChunkResult(stdout="", stderr="", error=f"{cwd_call}({nb_dir}) failed: {r['error']}")

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
        if c.language != lang:
            other = "py" if lang == "r" else "r"
            skipped.append(ChunkSkipped(index=c.index, label=c.label, language=c.language,
                                        reason=f"language={c.language}, use {other}:<name>"))
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


@mcp.tool()
def restart(session: str) -> Ack:
    """Kill and respawn the named session's worker — wipes the namespace.
    In slurm mode this scancels the allocation and resubmits under the
    current worker mode. Use after a worker crash or to deliberately reset
    state. Loses DB connections and loaded data, so use sparingly."""
    parsed = _parse_session(session)
    if parsed is None:
        return Ack(ok=False, message=_AMBIG)
    lang, bare = parsed
    s = _sessions.pop(f"{lang}:{bare}", None)
    if s is not None:
        _kill(s)
    return Ack(ok=True, message=f"restarted session '{session}'")


@mcp.tool()
def close(session: str) -> Ack:
    """Kill the named session's worker and release it — scancels the slurm
    allocation, terminates the process. Unlike restart,
    the worker is NOT respawned: the next run_code on this name starts a
    fresh session with an empty namespace. Never creates a session — closing
    a name that isn't running is a no-op success. Sessions are never
    auto-closed; call close when the task is done."""
    parsed = _parse_session(session)
    if parsed is None:
        return Ack(ok=False, message=_AMBIG)
    lang, bare = parsed
    s = _sessions.pop(f"{lang}:{bare}", None)
    if s is not None and _kill(s):
        return Ack(ok=True, message=f"closed session '{session}'")
    return Ack(ok=True, message=f"no running session '{session}'")


@mcp.tool()
def list_variables(session: str) -> VarList:
    """List variables in the session namespace with type/size/preview summaries."""
    parsed = _parse_session(session)
    if parsed is None:
        return VarList(variables=[], error=_AMBIG)
    lang, bare = parsed
    r = _call_worker(session, _LANGUAGES[lang]["list_vars"])
    if r.get("error"):
        return VarList(variables=[], error=r["error"])
    try:
        out = json.loads(r["stdout"].strip().split("\n")[-1])
        return VarList(variables=[VarSummary(**v) for v in out])
    except Exception:
        return VarList(variables=[], error="could not parse variable listing")


@mcp.tool()
def inspect_variable(session: str, name: str, path: list = None) -> InspectResult:
    """Inspect a variable — repr for Python sessions, str + head for R — optionally
    drilling by path (e.g. ['df','col'])."""
    parsed = _parse_session(session)
    if parsed is None:
        return InspectResult(name=name, repr="", error=_AMBIG)
    lang, bare = parsed
    code = _LANGUAGES[lang]["inspect"](name, path or [])
    r = _call_worker(session, code)
    return InspectResult(name=name, repr=r.get("stdout", ""), error=r.get("error"))


@mcp.tool()
def inject(session: str, path: str) -> Ack:
    """Exec a kernel.py / kernel.R sidecar into the session namespace — the
    extensibility mechanism for other skills. The sidecar should be top-level
    definitions only (lazy imports), no side-effect code at load."""
    with open(path, "r") as f:
        code = f.read()
    r = _call_worker(session, code)
    return Ack(ok=r.get("error") is None, message=r.get("error") or f"injected {path}")


if __name__ == "__main__":
    mcp.run()
