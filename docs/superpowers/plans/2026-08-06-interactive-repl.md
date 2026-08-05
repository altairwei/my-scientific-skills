# Interactive-REPL Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the `interactive-repl` foundation skill — a persistent R/Python REPL via two MCP servers — so the agent iterates in-session instead of re-running one-shot scripts.

**Architecture:** Two MCP stdio servers (`python-repl`, `r-repl`), each spawning worker subprocess(es) — one per named session — over a structured JSON protocol (stdin/stdout for Python, Unix socket for R). Subprocess isolation: a worker crash kills only the worker; the server survives and restarts it; the MCP connection stays up. Other skills extend the namespace via the `inject(path)` sidecar tool. Inline `mcpServers` on the `data-science` marketplace entry; `bioinformatics` is untouched.

**Tech Stack:** Python 3.10+, `mcp` SDK v2 (`from mcp.server import MCPServer`), `pydantic`, `uv run` with inline `# /// script` metadata; R 4.x for the R worker. Test stack: `pytest`, `pytest-asyncio`.

**Spec:** `docs/superpowers/specs/2026-08-05-interactive-repl-design.md` — read it for the *why* behind every choice here. This plan is the *how*.

**Confirmed API (probed against the installed `mcp` SDK v2):**
- `from mcp.server import MCPServer` → `mcp = MCPServer("name")`. (No `FastMCP` in v2.)
- `@mcp.tool()` decorator; type hints ARE the schema; docstring IS the description.
- **Return a Pydantic `BaseModel` for structured output** — a raw `dict` return yields `structured_content=None`; a `BaseModel` return yields `structured_content={...fields...}`. So every tool that returns structured data uses a Pydantic model.
- Tests: `from mcp import Client`; `async with Client(mcp) as client: r = await client.call_tool(name, args)`; read `r.structured_content` (the model as dict) or `r.content` (list of `TextContent` with JSON).
- Launch: `mcp.run()` (defaults to stdio) at the bottom of the server script.

---

## File Structure

```
data-science/interactive-repl/
├── SKILL.md                       # behavioral guidance (Phase 3)
├── references/
│   ├── tools.md                   # full tool API
│   ├── sidecar-authoring.md       # how to write a kernel.py/kernel.R for your skill
│   ├── r-setup.md                 # conda env, pkg::fun(), neutralized fns, scale_y_sqrt
│   ├── troubleshooting.md         # stuck code, missing deps, worker crashes, compaction
│   └── plot-iteration.md          # save-and-look, rendering semantics, Read-fail fallback
├── scripts/
│   ├── _common.py                 # shared: output capping, plot-dir mgmt, JSON framing, session pool
│   ├── python_repl_server.py      # MCPServer; session pool; proxies to python_worker.py
│   ├── python_worker.py            # namespace holder (adapted from wisp-science kernel_worker.py)
│   ├── r_repl_server.py           # MCPServer; session pool; proxies to R worker over Unix socket
│   ├── repl.R                      # R worker (withVisible+eval, ggsave, tryCatch, neutralize)
│   ├── kernel.py                   # base Python sidecar (peek/who/fig) — ref example
│   └── kernel.R                    # base R sidecar (who/peek/fig)
└── tests/
    ├── conftest.py                # shared spawn_worker helpers
    ├── test_common.py
    ├── test_python_worker.py
    ├── test_python_server.py
    ├── test_r_worker.py
    ├── test_r_server.py
    └── test_smoke.py              # end-to-end (Phase 3)
```

Each file has one responsibility. `_common.py` is the only shared module — pure helpers, no I/O, fully unit-testable. The two servers are thin adapters over `_common.py` + the language-specific worker protocol.

**Phases (natural shippable boundaries):**
- **Phase 1 — Python REPL** (Tasks 1–7): working persistent Python REPL, end-to-end.
- **Phase 2 — R REPL** (Tasks 8–11): working persistent R REPL, end-to-end.
- **Phase 3 — Ship** (Tasks 12–15): `SKILL.md`, `references/`, marketplace + README, smoke test.

---

## Phase 1 — Python REPL

### Task 1: Shared `_common.py` — output capping, plot-dir mgmt, JSON framing

**Files:**
- Create: `data-science/interactive-repl/scripts/_common.py`
- Test: `data-science/interactive-repl/tests/test_common.py`

- [ ] **Step 1: Write the failing tests**

```python
# data-science/interactive-repl/tests/test_common.py
from interactive_repl_scripts import _common  # see Step 3 for the import shim

def test_cap_output_truncates_with_marker():
    big = "x" * 1000
    out, truncated = _common.cap_output(big, max_bytes=100)
    assert len(out.encode()) <= 200
    assert truncated is True
    assert "truncated" in out.lower()

def test_cap_output_short_unchanged():
    out, truncated = _common.cap_output("hi", max_bytes=100)
    assert out == "hi" and truncated is False

def test_never_empty_returns_something_on_empty():
    # degraded output: if stdout is empty but stderr has content, surface stderr
    out = _common.never_empty("", "an error happened")
    assert "an error" in out

def test_plot_dir_is_under_data(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    d = _common.plot_dir()
    assert d.startswith(str(tmp_path))
    assert d.endswith("plots")

def test_json_line_roundtrip():
    msg = {"id": "x", "stdout": "hello\nworld", "error": None}
    line = _common.encode_line(msg)
    assert "\n" not in line  # single line
    assert _common.decode_line(line) == msg
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd data-science/interactive-repl && uv run --with pytest pytest tests/test_common.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'interactive_repl_scripts'`.

- [ ] **Step 3: Write minimal implementation**

Add an import shim so tests can `import` the scripts dir as a package. Create `data-science/interactive-repl/scripts/__init__.py` (empty) and `tests/conftest.py`:

```python
# data-science/interactive-repl/tests/conftest.py
import sys, pathlib
SCRIPTS = pathlib.Path(__file__).parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
```

```python
# data-science/interactive-repl/scripts/_common.py
"""Shared helpers for the interactive-repl MCP servers (pure, no I/O)."""
import json, os

def cap_output(text: str, max_bytes: int = 1024 * 1024) -> tuple[str, bool]:
    """Cap text to ~max_bytes UTF-8; append a marker if truncated. Returns (text, truncated)."""
    b = text.encode("utf-8", "surrogatepass")
    if len(b) <= max_bytes:
        return text, False
    head = b[:max_bytes].decode("utf-8", "ignore")
    dropped = len(b) - max_bytes
    return f"{head}\n... (truncated, {dropped} further bytes dropped)", True

def never_empty(stdout: str, stderr: str) -> str:
    """If stdout is empty, surface stderr (degraded). Never return empty."""
    if stdout.strip():
        return stdout
    if stderr.strip():
        return f"[stderr only]\n{stderr}"
    return "[no output]"

def plot_dir() -> str:
    """Persistent plot directory under ${CLAUDE_PLUGIN_DATA}/plots (or a temp fallback)."""
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or "/tmp/interactive-repl-data"
    d = os.path.join(base, "plots")
    os.makedirs(d, exist_ok=True)
    return d

def encode_line(obj: dict) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"

def decode_line(line: str) -> dict:
    return json.loads(line)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd data-science/interactive-repl && uv run --with pytest pytest tests/test_common.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add data-science/interactive-repl/scripts/_common.py data-science/interactive-repl/scripts/__init__.py data-science/interactive-repl/tests/conftest.py data-science/interactive-repl/tests/test_common.py
git commit -m "Add interactive-repl _common.py: output capping, plot-dir, JSON framing"
```

---

### Task 2: Python worker — namespace, exec/eval heuristic, JSON-line protocol, tryCatch-guarantees-response

**Files:**
- Create: `data-science/interactive-repl/scripts/python_worker.py`
- Test: `data-science/interactive-repl/tests/test_python_worker.py`

The worker is adapted directly from wisp-science's `python/kernel_worker.py` (read it in `external/wisp-science/python/kernel_worker.py` for reference). JSON-per-line stdin/stdout; the protocol pipes are duped off fd 0/1 so user subprocesses don't corrupt the stream.

- [ ] **Step 1: Write the failing tests**

```python
# data-science/interactive-repl/tests/test_python_worker.py
import json, subprocess, sys, pathlib, textwrap
HERE = pathlib.Path(__file__).parent
WORKER = HERE.parent / "scripts" / "python_worker.py"

def _spawn():
    return subprocess.Popen(
        [sys.executable, str(WORKER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )

def _call(p, code: str, rid="t") -> dict:
    p.stdin.write(json.dumps({"id": rid, "code": code}) + "\n")
    p.stdin.flush()
    line = p.stdout.readline()
    return json.loads(line)

def test_roundtrip_simple_expression():
    p = _spawn()
    try:
        assert p.stdout.readline().startswith("[repl]")  # ready marker
        r = _call(p, "1 + 1")
        assert r["id"] == "t"
        assert r["error"] is None
        assert "2" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()

def test_persistent_state_across_calls():
    p = _spawn()
    try:
        p.stdout.readline()
        _call(p, "x = 42")
        r = _call(p, "x * 2")
        assert "84" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()

def test_error_still_returns_response():
    p = _spawn()
    try:
        p.stdout.readline()
        r = _call(p, "raise ValueError('boom')")
        assert r["error"] is not None
        assert "boom" in r["error"]
        # session still usable after error
        r2 = _call(p, "1 + 1")
        assert r2["error"] is None and "2" in r2["stdout"]
    finally:
        p.stdin.close(); p.terminate()

def test_multiline_exec():
    p = _spawn()
    try:
        p.stdout.readline()
        r = _call(p, "y = 0\nfor i in range(3): y += i\ny")
        assert r["error"] is None
        assert "3" in r["stdout"]  # 0+1+2
    finally:
        p.stdin.close(); p.terminate()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd data-science/interactive-repl && uv run --with pytest pytest tests/test_python_worker.py -v`
Expected: FAIL (worker doesn't exist / no ready marker).

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
# data-science/interactive-repl/scripts/python_worker.py
# /// script
# requires-python = ">=3.10"
# ///
"""Persistent Python namespace over a JSON-per-line stdin/stdout protocol.

Request:  {"id": "<rid>", "code": "<python source>"}
Response: {"id": "<rid>", "stdout": "...", "stderr": "...", "error": null|"<traceback>",
           "plots": ["/path/to/fig.png"], "truncated": false, "degraded": false}

Protocol pipes are duped off fd 0/1 so user subprocesses inheriting them don't
corrupt the stream. Errors are caught — the response ALWAYS returns (no hangs).
"""
import builtins, io, json, os, sys, time, traceback

# Force Agg BEFORE matplotlib is ever imported (so plt.show() / GUI backends can't block).
os.environ["MPLBACKEND"] = "Agg"

MAX_OUTPUT = 1024 * 1024  # 1 MB head cap

_EXEC_PREFIXES = ("import ", "from ", "def ", "class ", "if ", "for ", "while ",
                  "with ", "try:", "try ", "except ", "finally:", "elif ", "else:",
                  "raise ", "return ", "del ", "global ", "nonlocal ", "assert ",
                  "async ", "match ", "case ", "yield ", "@")

def _looks_like_exec(code: str) -> bool:
    s = code.strip()
    if not s or "\n" in s:
        return True
    return any(s.lstrip().startswith(p) for p in _EXEC_PREFIXES)

def _execute_cell(code, cell_tag, namespace):
    if _looks_like_exec(code):
        exec(compile(code, cell_tag, "exec"), namespace)
        return
    try:
        result = eval(compile(code, cell_tag, "eval"), namespace)
    except SyntaxError:
        exec(compile(code, cell_tag, "exec"), namespace)
        return
    if result is not None:
        print(repr(result))

def _configure_pandas():
    try:
        import pandas as pd
        pd.set_option("display.max_columns", None)
        pd.set_option("display.max_rows", 500)
        pd.set_option("display.max_colwidth", None)
        pd.set_option("display.width", None)
        pd.set_option("display.expand_frame_repr", False)
    except Exception:
        pass

def _neutralize_pyplot_show():
    try:
        plt = sys.modules.get("matplotlib.pyplot")
    except Exception:
        plt = None
    if not plt:
        return
    show = getattr(plt, "show", None)
    if getattr(show, "_repl_noop", False):
        return
    def _noop(*_a, **_k):
        return None
    _noop._repl_noop = True
    plt.show = _noop

def _capture_new_figures():
    """Return (paths, close) for any matplotlib figures created since last call."""
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return []
    nums = plt.get_fignums()
    if not nums:
        return []
    paths = []
    import os, uuid
    from interactive_repl_scripts import _common  # for plot_dir
    pdir = _common.plot_dir()
    for n in nums:
        fig = plt.figure(n)
        path = os.path.join(pdir, f"fig-{n}-{uuid.uuid4().hex[:8]}.png")
        try:
            fig.savefig(path, dpi=110, bbox_inches="tight")
            paths.append(path)
        except Exception:
            pass
        plt.close(fig)
    return paths

def main():
    # Move protocol pipes off fd 0/1 so user subprocesses can't corrupt them.
    protocol_in = os.fdopen(os.dup(0), "r", encoding="utf-8", errors="replace")
    protocol_out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)

    print("[repl] ready", file=sys.stderr, flush=True)

    namespace = {"__name__": "__main__", "__builtins__": __builtins__}
    import json as _j, math, os as _os, re, sys as _sys, urllib.parse, urllib.request
    namespace.update({"json": _j, "math": math, "os": _os, "re": re, "sys": _sys,
                      "urllib": type(urllib) and __import__("urllib")})
    for mod in ("numpy", "pandas"):
        try:
            namespace[mod] = __import__(mod)
        except ImportError:
            pass

    # Lazy import hook: configure pandas / neutralize plt.show on first import.
    _orig_import = builtins.__import__
    def import_wrapper(name, *a, **k):
        mod = _orig_import(name, *a, **k)
        if name == "pandas":
            _configure_pandas()
        elif name.startswith("matplotlib"):
            _neutralize_pyplot_show()
        return mod
    builtins.__import__ = import_wrapper

    import linecache as _lc
    counter = 0
    while True:
        line = protocol_in.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            protocol_out.write(json.dumps({"id": "unknown", "stdout": "",
                "stderr": "", "error": f"Invalid JSON: {e}", "plots": [],
                "truncated": False, "degraded": False}) + "\n")
            protocol_out.flush()
            continue
        rid = req.get("id", "unknown")
        code = req.get("code", "")
        counter += 1
        cell_tag = f"<repl:{counter}>"
        _lc.cache[cell_tag] = (len(code), None, code.splitlines(True), cell_tag)

        out_cap, err_cap = io.StringIO(), io.StringIO()
        error = None
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = out_cap, err_cap
            _execute_cell(code, cell_tag, namespace)
        except BaseException:
            error = traceback.format_exc()
        finally:
            sys.stdout, sys.stderr = old_out, old_err

        plots = _capture_new_figures()

        from interactive_repl_scripts import _common
        stdout, truncated = _common.cap_output(out_cap.getvalue())
        stderr = err_cap.getvalue()
        degraded = not out_cap.getvalue().strip() and bool(stderr.strip())
        stdout = _common.never_empty(stdout, stderr) if degraded else stdout
        protocol_out.write(json.dumps({
            "id": rid, "stdout": stdout, "stderr": stderr, "error": error,
            "plots": plots, "truncated": truncated, "degraded": degraded,
        }) + "\n")
        protocol_out.flush()

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd data-science/interactive-repl && uv run --with pytest --with numpy pytest tests/test_python_worker.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add data-science/interactive-repl/scripts/python_worker.py data-science/interactive-repl/tests/test_python_worker.py
git commit -m "Add python_worker.py: persistent namespace, exec/eval, tryCatch-guarantees-response"
```

---

### Task 3: Python worker — plot capture + import-hook tests (TDD for the novel bits)

**Files:**
- Test: `data-science/interactive-repl/tests/test_python_worker.py` (extend)

- [ ] **Step 1: Write the failing tests (append)**

```python
# append to tests/test_python_worker.py
def test_matplotlib_figure_captured_to_png(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    p = _spawn()
    try:
        p.stdout.readline()
        r = _call(p, "import matplotlib.pyplot as plt; plt.plot([1,2,3]); plt.xlabel('x')")
        assert r["error"] is None
        assert len(r["plots"]) >= 1
        import os
        assert os.path.exists(r["plots"][0])
        # figure closed — a second call with no new figure returns no plots
        r2 = _call(p, "1 + 1")
        assert r2["plots"] == []
    finally:
        p.stdin.close(); p.terminate()

def test_plt_show_is_noop():
    p = _spawn()
    try:
        p.stdout.readline()
        # plt.show() must not block — if it did, the call would hang/timeout
        r = _call(p, "import matplotlib.pyplot as plt; plt.plot([1,2]); plt.show()")
        assert r["error"] is None
    finally:
        p.stdin.close(); p.terminate()
```

- [ ] **Step 2: Run the tests to verify they fail/pass**

Run: `cd data-science/interactive-repl && uv run --with pytest --with numpy --with matplotlib pytest tests/test_python_worker.py -v`
Expected: PASS (Task 2's implementation already covers these — if they fail, fix the plot-capture logic in `python_worker.py`).

- [ ] **Step 3: Commit**

```bash
git add data-science/interactive-repl/tests/test_python_worker.py
git commit -m "Test python_worker plot capture + plt.show noop"
```

---

### Task 4: Python server — `MCPServer` skeleton, session pool, `run_code`/`session_info`/`restart`

**Files:**
- Create: `data-science/interactive-repl/scripts/python_repl_server.py`
- Test: `data-science/interactive-repl/tests/test_python_server.py`

- [ ] **Step 1: Write the failing tests**

```python
# data-science/interactive-repl/tests/test_python_server.py
import asyncio, os, sys, pathlib
HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import pytest

@pytest.mark.asyncio
async def test_run_code_auto_starts_session(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "t1", "code": "1 + 1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]

@pytest.mark.asyncio
async def test_persistence_across_calls(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "t2", "code": "x = 10"})
        r = await client.call_tool("run_code", {"session": "t2", "code": "x * 5"})
        assert "50" in r.structured_content["stdout"]

@pytest.mark.asyncio
async def test_named_sessions_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "a", "code": "y = 1"})
        await client.call_tool("run_code", {"session": "b", "code": "y = 2"})
        ra = await client.call_tool("run_code", {"session": "a", "code": "y"})
        rb = await client.call_tool("run_code", {"session": "b", "code": "y"})
        assert "1" in ra.structured_content["stdout"]
        assert "2" in rb.structured_content["stdout"]

@pytest.mark.asyncio
async def test_restart_clears_state(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "t3", "code": "z = 99"})
        await client.call_tool("restart", {"session": "t3"})
        r = await client.call_tool("run_code", {"session": "t3", "code": "z"})
        assert r.structured_content["error"] is not None  # NameError after restart
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with numpy pytest tests/test_python_server.py -v`
Expected: FAIL (`ModuleNotFoundError: No module named 'python_repl_server'`).

- [ ] **Step 3: Write minimal implementation**

```python
#!/usr/bin/env python3
# data-science/interactive-repl/scripts/python_repl_server.py
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp", "pydantic"]
# ///
"""python-repl MCP stdio server. Spawns python_worker.py per named session."""
import asyncio, json, os, subprocess, sys, uuid
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
    # wait for the [repl] ready marker
    ready = p.stdout.readline()
    if not ready.startswith("[repl]"):
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
        p.stdin.write(json.dumps({"id": rid, "code": code}) + "\n")
        p.stdin.flush()
        line = p.stdout.readline()
    except (BrokenPipeError, OSError) as e:
        # worker died — restart and tell the caller
        _sessions.pop(session, None)
        return {"stdout": "", "stderr": "", "error": f"worker died: {e}",
                "plots": [], "truncated": False, "degraded": False}
    if not line:
        _sessions.pop(session, None)
        return {"stdout": "", "stderr": "", "error": "worker died (no output)",
                "plots": [], "truncated": False, "degraded": False}
    return json.loads(line)


@mcp.tool()
def run_code(session: str, code: str, timeout: int = 300) -> RunResult:
    """Execute Python code in a persistent REPL session. Variables, imports, and
    loaded data persist across calls. Returns stdout, stderr, error (traceback or
    None), plots (saved-PNG paths), and truncated/degraded flags. The session is
    auto-created on first call. Use distinct session names per task."""
    r = _call_worker(session, code)
    return RunResult(**{k: r.get(k) for k in RunResult.model_fields})


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
    Use after a worker crash or to deliberately reset state. Loses DB connections
    and loaded data, so use sparingly."""
    p = _sessions.pop(session, None)
    if p is not None:
        try:
            p.terminate(); p.wait(timeout=2)
        except Exception:
            pass
    return Ack(ok=True, message=f"restarted session '{session}'")


if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy pytest tests/test_python_server.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add data-science/interactive-repl/scripts/python_repl_server.py data-science/interactive-repl/tests/test_python_server.py
git commit -m "Add python_repl_server: MCPServer, session pool, run_code/session_info/restart"
```

---

### Task 5: Python server — `list_variables`, `inspect_variable`, `inject`

**Files:**
- Modify: `data-science/interactive-repl/scripts/python_repl_server.py`
- Test: `data-science/interactive-repl/tests/test_python_server.py` (extend)

- [ ] **Step 1: Write the failing tests (append)**

```python
# append to tests/test_python_server.py
@pytest.mark.asyncio
async def test_list_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "lv", "code": "a = 1; b = [1,2,3]"})
        r = await client.call_tool("list_variables", {"session": "lv"})
        names = [v["name"] for v in r.structured_content["variables"]]
        assert "a" in names and "b" in names

@pytest.mark.asyncio
async def test_inject_sidecar(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    sidecar = tmp_path / "k.py"; sidecar.write_text("def hello():\n    return 'injected'\n")
    async with Client(mcp) as client:
        await client.call_tool("inject", {"session": "inj", "path": str(sidecar)})
        r = await client.call_tool("run_code", {"session": "inj", "code": "hello()"})
        assert "injected" in r.structured_content["stdout"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy pytest tests/test_python_server.py::test_list_variables tests/test_python_server.py::test_inject_sidecar -v`
Expected: FAIL (`list_variables` / `inject` tools don't exist).

- [ ] **Step 3: Add the tools to `python_repl_server.py`**

Add these models and tools (the `inspect_variable` body is built via code injection — the simplest robust approach, mirroring r-cell's `status`-via-code pattern):

```python
# add to python_repl_server.py models
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
```

```python
# add to python_repl_server.py, after run_code
_PEEK_SRC = """
import builtins as _b
def _repl_peek(obj, path=None):
    o = obj
    if path:
        for p in path:
            o = o[p] if isinstance(p, int) else getattr(o, p)
    t = type(o).__name__
    try:
        n = len(o)
    except Exception:
        n = ''
    has_kids = hasattr(o, '__len__') and n != 0 and not isinstance(o, (str, bytes))
    try:
        prev = repr(o)[:200]
    except Exception as e:
        prev = f'<unrepr-able: {e}>'
    return {'name': t, 'type': t, 'size': str(n), 'preview': prev, 'has_children': bool(has_kids)}
_b._repl_peek = _repl_peek
"""

@mcp.tool()
def list_variables(session: str) -> VarList:
    """List the variables in the session namespace with type/size/preview summaries."""
    r = _call_worker(session, _PEEK_SRC)
    if r.get("error"):
        return VarList(variables=[])
    # now ask for each top-level name
    names_r = _call_worker(session,
        "import json as _j; _j.dumps([(n, _repl_peek(v)) for n,v in sorted(vars(__main__).items()) if not n.startswith('_')])")
    if names_r.get("error"):
        return VarList(variables=[])
    import json as _j
    pairs = _j.loads(names_r["stdout"].strip().split("\n")[-1])
    return VarList(variables=[VarSummary(**p[1] | {"name": p[0]}) for p in pairs])

@mcp.tool()
def inspect_variable(session: str, name: str, path: list = None) -> InspectResult:
    """Drill into a variable by path (e.g. ['df','colname'] or ['lst',0])."""
    code = f"_repl_peek({name}, path={path})"
    r = _call_worker(session, code)
    return InspectResult(name=name, repr=r.get("stdout",""), error=r.get("error"))

@mcp.tool()
def inject(session: str, path: str) -> Ack:
    """Exec a kernel.py sidecar into the session namespace — the extensibility
    mechanism for other skills. The sidecar should be top-level definitions only
    (lazy imports), no side-effect code."""
    with open(path, "r") as f:
        code = f.read()
    r = _call_worker(session, code)
    return Ack(ok=r.get("error") is None,
               message=r.get("error") or f"injected {path}")
```

Also: register `_PEEK_SRC` at session start (run it once when a worker starts). Modify `_start` to send `_PEEK_SRC` as the first cell after the ready marker:

```python
def _start(session: str) -> subprocess.Popen:
    p = subprocess.Popen(
        [sys.executable, str(WORKER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    ready = p.stdout.readline()
    if not ready.startswith("[repl]"):
        raise RuntimeError(f"worker failed to start: {ready!r} {p.stderr.read()!r}")
    # inject the _repl_peek helper at session start
    p.stdin.write(json.dumps({"id": "init", "code": _PEEK_SRC}) + "\n")
    p.stdin.flush()
    p.stdout.readline()  # discard the init response
    return p
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy pytest tests/test_python_server.py -v`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add data-science/interactive-repl/scripts/python_repl_server.py data-science/interactive-repl/tests/test_python_server.py
git commit -m "Add list_variables/inspect_variable/inject to python_repl_server"
```

---

### Task 6: Base `kernel.py` sidecar — `peek`/`who`/`fig` (reference sidecar)

**Files:**
- Create: `data-science/interactive-repl/scripts/kernel.py`
- Test: `data-science/interactive-repl/tests/test_kernel_sidecar.py`

The base sidecar is itself a `kernel.py` — definition-only, lazy imports — auto-injected at session start, and a reference example for sidecar authoring.

- [ ] **Step 1: Write the failing test**

```python
# data-science/interactive-repl/tests/test_kernel_sidecar.py
import asyncio, sys, pathlib
HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "scripts"))
import pytest

@pytest.mark.asyncio
async def test_base_sidecar_loaded_at_start(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        # _peek, _who, _fig should be available without an explicit inject
        r = await client.call_tool("run_code", {"session": "sc", "code": "_who()"})
        sc = r.structured_content
        # _who() returns a string listing vars (or empty) — no NameError
        assert sc["error"] is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy pytest tests/test_kernel_sidecar.py -v`
Expected: FAIL (`_who` not defined — only `_repl_peek` is injected at start).

- [ ] **Step 3: Write the base sidecar and wire auto-injection**

```python
# data-science/interactive-repl/scripts/kernel.py
"""Base interactive-repl sidecar — auto-injected into every python-repl session.
Definition-only, lazy imports — also the reference example for sidecar authoring
(see references/sidecar-authoring.md)."""

def _who():
    """List session variables (name + type), excluding underscore-prefixed."""
    import builtins as _b
    ns = _b.__main__.__dict__ if hasattr(_b, '__main__') else None
    g = globals()
    return "\n".join(f"{n}\t{type(v).__name__}" for n, v in sorted(g.items())
                     if not n.startswith("_") and not callable(v))

def _peek(obj):
    """Type-dispatched summary: DataFrame→shape+dtypes+head, list→len+first, else repr."""
    t = type(obj).__name__
    if t == "DataFrame":
        return f"DataFrame {obj.shape}\n{obj.dtypes.to_string()}\n{obj.head()}"
    if hasattr(obj, "__len__"):
        return f"{t} len={len(obj)}\n{repr(obj)[:200]}"
    return repr(obj)[:200]

def _fig(n=0):
    """Return the path of the nth saved figure in this session's plot dir."""
    import os, glob
    from interactive_repl_scripts import _common
    fs = sorted(glob.glob(os.path.join(_common.plot_dir(), "fig-*.png")))
    return fs[n] if fs else None
```

Wire auto-injection: in `python_repl_server.py`, read `kernel.py` at server import and include it in `_start`'s init cells. Add after the `_PEEK_SRC` cell in `_start`:

```python
def _base_sidecar_src() -> str:
    p = HERE / "kernel.py"
    return p.read_text() if p.exists() else ""

# in _start, after the _PEEK_SRC init cell:
    for code in (_PEEK_SRC, _base_sidecar_src()):
        if code:
            p.stdin.write(json.dumps({"id": "init", "code": code}) + "\n")
            p.stdin.flush()
            p.stdout.readline()  # discard init response
```

(Replace the single `_PEEK_SRC` init block from Task 5 with this loop.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy pytest tests/test_kernel_sidecar.py tests/test_python_server.py -v`
Expected: PASS (sidecar loaded; existing server tests still pass).

- [ ] **Step 5: Commit**

```bash
git add data-science/interactive-repl/scripts/kernel.py data-science/interactive-repl/scripts/python_repl_server.py data-science/interactive-repl/tests/test_kernel_sidecar.py
git commit -m "Add base kernel.py sidecar (peek/who/fig), auto-inject at session start"
```

---

### Task 7: Phase 1 smoke — end-to-end Python REPL via stdio launch

**Files:**
- Test: `data-science/interactive-repl/tests/test_smoke.py`

- [ ] **Step 1: Write the smoke test (launches the real server over stdio)**

```python
# data-science/interactive-repl/tests/test_smoke.py
"""Phase-1 smoke: launch python_repl_server.py over stdio (as the plugin would)
and call run_code via a real stdio Client — not the in-memory Client(mcp)."""
import json, subprocess, sys, pathlib, pytest

HERE = pathlib.Path(__file__).parent
SERVER = HERE.parent / "scripts" / "python_repl_server.py"

def _stdio_call(proc, name, args):
    proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":1,"method":"tools/call",
        "params":{"name":name,"arguments":args}}) + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())

@pytest.mark.asyncio  # noqa — sync test, but keep pytest discovery uniform
def test_python_repl_stdio_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    proc = subprocess.Popen(
        ["uv", "run", str(SERVER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    try:
        # initialize handshake (minimal)
        proc.stdin.write(json.dumps({"jsonrpc":"2.0","id":0,"method":"initialize",
            "params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"0"}}}) + "\n")
        proc.stdin.flush(); proc.stdout.readline()  # init response
        proc.stdin.write(json.dumps({"jsonrpc":"2.0","method":"notifications/initialized"}) + "\n")
        proc.stdin.flush()
        # call run_code
        r = _stdio_call(proc, "run_code", {"session":"smoke","code":"2 + 2"})
        # result.content[0].text holds JSON
        import json as _j
        text = r["result"]["content"][0]["text"]
        parsed = _j.loads(text)
        assert parsed["error"] is None
        assert "4" in parsed["stdout"]
    finally:
        proc.terminate()
```

- [ ] **Step 2: Run the smoke test**

Run: `cd data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy pytest tests/test_smoke.py -v`
Expected: PASS. If it fails on the handshake, adjust the `initialize` params to match the SDK's expected protocol version (check `mcp`'s source) — the in-memory `Client(mcp)` tests in Tasks 4–6 already prove the tool surface works; this test only validates the stdio launch path.

- [ ] **Step 3: Commit**

```bash
git add data-science/interactive-repl/tests/test_smoke.py
git commit -m "Add Phase-1 stdio smoke test for python_repl_server"
```

**Phase 1 complete:** a working persistent Python REPL, end-to-end, with tests. This is shippable as v0.1.

---

## Phase 2 — R REPL

### Task 8: R worker — `repl.R` JSON-over-Unix-socket, `withVisible`+`eval`, `tryCatch`, never-empty

**Files:**
- Create: `data-science/interactive-repl/scripts/repl.R`
- Test: `data-science/interactive-repl/tests/test_r_worker.py`

The R worker connects to a Unix socket the server creates, reads JSON requests, evals with `tryCatch` (response always returns), captures output, saves plots, writes JSON responses. The eval logic is adapted from `external/r-cell/r-cell.sh`'s `_build_wrapper` (withVisible + eval in globalenv + ggsave on ggplot).

- [ ] **Step 1: Write the failing tests**

```python
# data-science/interactive-repl/tests/test_r_worker.py
import json, os, socket, subprocess, sys, pathlib, time, pytest
HERE = pathlib.Path(__file__).parent
REPL_R = HERE.parent / "scripts" / "repl.R"

def _spawn_and_connect(tmp_path):
    sock_path = str(tmp_path / "repl.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path); srv.listen(1); srv.settimeout(15)
    # spawn R worker pointing at the socket
    proc = subprocess.Popen(
        ["R", "--no-save", "--no-restore", "-f", str(REPL_R)],
        env={**os.environ, "REPL_SOCKET": sock_path},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    conn, _ = srv.accept()
    return proc, conn

def _call(conn, code, rid="t"):
    conn.sendall((json.dumps({"id": rid, "code": code}) + "\n").encode())
    line = b""
    while not line.endswith(b"\n"):
        line += conn.recv(65536)
    return json.loads(line.decode())

def test_r_roundtrip(tmp_path):
    proc, conn = _spawn_and_connect(tmp_path)
    try:
        r = _call(conn, "1 + 1")
        assert r["error"] is None
        assert "2" in r["stdout"]
    finally:
        proc.terminate(); conn.close()

def test_r_persistence(tmp_path):
    proc, conn = _spawn_and_connect(tmp_path)
    try:
        _call(conn, "x <- 42")
        r = _call(conn, "x * 2")
        assert "84" in r["stdout"]
    finally:
        proc.terminate(); conn.close()

def test_r_error_returns_response(tmp_path):
    proc, conn = _spawn_and_connect(tmp_path)
    try:
        r = _call(conn, "stop('boom')")
        assert r["error"] is not None and "boom" in r["error"]
        r2 = _call(conn, "1 + 1")
        assert r2["error"] is None  # session still usable
    finally:
        proc.terminate(); conn.close()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd data-science/interactive-repl && uv run --with pytest pytest tests/test_r_worker.py -v`
Expected: FAIL (`repl.R` doesn't exist / can't connect).

- [ ] **Step 3: Write `repl.R`**

```r
#!/usr/bin/env Rscript
# data-science/interactive-repl/scripts/repl.R
# Persistent R namespace over a JSON-per-line Unix-socket protocol.
# Env: REPL_SOCKET = path to a Unix socket the server created and listens on.

con <- socketConnection(host = "localhost", basename(Sys.getenv("REPL_SOCKET")),
                        server = FALSE, blocking = TRUE, open = "r+b")
on.exit(close(con))

options(width = 400)  # wide so captured R lines don't wrap

write_json <- function(obj) {
  cat(jsonlite::toJSON(obj, auto_unbox = TRUE, null = "null"), "\n", sep = "", file = con)
}

run_cell <- function(code) {
  out <- ""; err <- ""; plots <- character(0); error_msg <- NULL
  stdout_con <- textConnection("out", "w", local = TRUE)
  sink(stdout_con, type = "output"); on.exit(sink(type = "output"), add = TRUE)
  tryCatch({
    ex <- parse(text = code)
    for (i in seq_along(ex)) {
      r <- withVisible(eval(ex[[i]], envir = globalenv()))
      if (isTRUE(r$visible)) {
        if (inherits(r$value, "ggplot")) {
          f <- tempfile(fileext = ".png")
          ggplot2::ggsave(f, r$value, width = 12, height = 8, dpi = 110)
          cat("FIGURE saved:", f, "\n")
          plots <- c(plots, f)
        } else {
          print(r$value)
        }
      }
    }
  }, error = function(e) {
    error_msg <<- conditionMessage(e)
  })
  sink()  # flush output capture
  close(stdout_con)
  # never-empty: if stdout is empty but there's an error, surface the error
  if (!nzchar(out) && !is.null(error_msg)) out <- paste0("ERROR: ", error_msg)
  list(stdout = out, stderr = "", error = error_msg, plots = plots,
       truncated = FALSE, degraded = FALSE)
}

# Neutralize interactive R functions that block/error headless (r-cell lesson).
dt_table_override <- function() {
  dt_table <- function(df, digits = NULL, caption = NULL, ...) {
    if (!is.null(caption)) cat("## ", caption, "\n", sep = "")
    print(knitr::kable(df))
  }
  assign("dt_table", dt_table, envir = globalenv())
}
dt_table_override()

cat("[repl] ready\n", file = con)
repeat {
  line <- readLines(con, n = 1)
  if (length(line) == 0 || !nzchar(line)) next
  req <- tryCatch(jsonlite::fromJSON(line), error = function(e) NULL)
  if (is.null(req)) {
    write_json(list(id = "unknown", stdout = "", stderr = "",
                    error = "Invalid JSON", plots = character(0),
                    truncated = FALSE, degraded = FALSE)); next
  }
  rid <- req$id %||% "unknown"
  res <- tryCatch(run_cell(req$code), error = function(e) {
    list(stdout = "", stderr = "", error = conditionMessage(e),
         plots = character(0), truncated = FALSE, degraded = FALSE)
  })
  res$id <- rid
  write_json(res)
}
```

Note: `` `%||%` `` is `rlang`'s null-coalesce; if `rlang` isn't available, define it: `` `%||%` <- function(a, b) if (is.null(a)) b else a ``. Add this near the top of `repl.R`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd data-science/interactive-repl && uv run --with pytest --with numpy --with matplotlib --with pandas pytest tests/test_r_worker.py -v`
Expected: PASS (3 tests). If `jsonlite`/`knitr`/`ggplot2` aren't installed in the R env, install them first (`install.packages(c("jsonlite","knitr","ggplot2"))` in the test R session) — or skip the ggsave test if ggplot2 is absent.

- [ ] **Step 5: Commit**

```bash
git add data-science/interactive-repl/scripts/repl.R data-science/interactive-repl/tests/test_r_worker.py
git commit -m "Add repl.R: persistent R worker over Unix socket, withVisible+eval, tryCatch"
```

---

### Task 9: R worker — ggsave + `dt_table` neutralization tests

**Files:**
- Test: `data-science/interactive-repl/tests/test_r_worker.py` (extend)

- [ ] **Step 1: Write the failing tests (append)**

```python
# append to tests/test_r_worker.py
def test_r_ggplot_saved_to_png(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    proc, conn = _spawn_and_connect(tmp_path)
    try:
        r = _call(conn,
          "library(ggplot2); p <- ggplot(data.frame(x=1:3,y=c(1,4,9)), aes(x,y)) + geom_point() + geom_line(); print(p)")
        assert r["error"] is None
        assert any(p.endswith(".png") for p in r["plots"])
        import os
        assert os.path.exists(r["plots"][0])
    finally:
        proc.terminate(); conn.close()

def test_dt_table_overridden_to_kable(tmp_path):
    proc, conn = _spawn_and_connect(tmp_path)
    try:
        r = _call(conn, "dt_table(data.frame(a=1:3, b=c('x','y','z')))")
        assert r["error"] is None
        assert "|" in r["stdout"]  # kable prints a markdown-style table
    finally:
        proc.terminate(); conn.close()
```

- [ ] **Step 2: Run the tests to verify they pass**

Run: `cd data-science/interactive-repl && uv run --with pytest pytest tests/test_r_worker.py -v`
Expected: PASS (Task 8 already covers ggsave + dt_table override; if they fail, fix `run_cell` / `dt_table_override` in `repl.R`).

- [ ] **Step 3: Commit**

```bash
git add data-science/interactive-repl/tests/test_r_worker.py
git commit -m "Test repl.R ggsave capture + dt_table→kable neutralization"
```

---

### Task 10: R server — `MCPServer`, session pool, proxies to R worker over Unix socket

**Files:**
- Create: `data-science/interactive-repl/scripts/r_repl_server.py`
- Test: `data-science/interactive-repl/tests/test_r_server.py`

- [ ] **Step 1: Write the failing tests**

```python
# data-science/interactive-repl/tests/test_r_server.py
import asyncio, sys, pathlib, pytest
HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "scripts"))

@pytest.mark.asyncio
async def test_r_run_code(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from r_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "r1", "code": "1 + 1"})
        assert r.structured_content["error"] is None
        assert "2" in r.structured_content["stdout"]

@pytest.mark.asyncio
async def test_r_persistence_and_list_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from r_repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "r2", "code": "df <- data.frame(a=1:3)"})
        r = await client.call_tool("list_variables", {"session": "r2"})
        names = [v["name"] for v in r.structured_content["variables"]]
        assert "df" in names

@pytest.mark.asyncio
async def test_r_inject_sidecar(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from r_repl_server import mcp
    sidecar = tmp_path / "k.R"; sidecar.write_text("hello_r <- function() 'injected'\n")
    async with Client(mcp) as client:
        await client.call_tool("inject", {"session": "r3", "path": str(sidecar)})
        r = await client.call_tool("run_code", {"session": "r3", "code": "hello_r()"})
        assert "injected" in r.structured_content["stdout"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy pytest tests/test_r_server.py -v`
Expected: FAIL (no `r_repl_server`).

- [ ] **Step 3: Write `r_repl_server.py`**

Mirror `python_repl_server.py`'s structure (Task 4–5), but the worker is an R process driven over a Unix socket instead of stdin/stdout JSON-lines:

```python
#!/usr/bin/env python3
# data-science/interactive-repl/scripts/r_repl_server.py
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp", "pydantic"]
# ///
"""r-repl MCP stdio server. Spawns an R worker (repl.R) per named session,
driven over a Unix socket."""
import json, os, socket, subprocess, sys, uuid
from pathlib import Path
from pydantic import BaseModel, Field
from mcp.server import MCPServer

HERE = Path(__file__).resolve().parent
REPL_R = HERE / "repl.R"
sys.path.insert(0, str(HERE))
import _common  # noqa: E402

mcp = MCPServer("r-repl")

class _Session:
    def __init__(self, proc, sock_path, conn):
        self.proc = proc; self.sock_path = sock_path; self.conn = conn

_sessions: dict[str, _Session] = {}


# Result models — same shape as python_repl_server
class RunResult(BaseModel):
    stdout: str; stderr: str; error: str | None = None
    plots: list[str] = Field(default_factory=list)
    truncated: bool = False; degraded: bool = False
class VarSummary(BaseModel):
    name: str; type: str; size: str = ""; preview: str = ""; has_children: bool = False
class VarList(BaseModel):
    variables: list[VarSummary]
class InspectResult(BaseModel):
    name: str; repr: str; error: str | None = None
class Ack(BaseModel):
    ok: bool; message: str = ""
class SessionInfo(BaseModel):
    session: str; running: bool; pid: int | None = None; plot_dir: str = ""


def _start(session: str) -> _Session:
    sock_path = os.path.join(_common.plot_dir(), f"r-{session}-{uuid.uuid4().hex[:6]}.sock")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(sock_path); srv.listen(1); srv.settimeout(15)
    r_env = os.environ.get("INTERACTIVE_REPL_R_ENV")
    r_bin = os.environ.get("INTERACTIVE_REPL_R_BIN", "R")
    argv = [r_bin, "--no-save", "--no-restore", "-f", str(REPL_R)]
    env = {**os.environ, "REPL_SOCKET": sock_path}
    if r_env:
        argv = ["conda", "run", "-n", r_env, "--no-capture-output", *argv]
    proc = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True)
    conn, _ = srv.accept()
    # read [repl] ready marker
    ready = conn.recv(256)
    if b"[repl] ready" not in ready:
        raise RuntimeError(f"R worker failed to start: {ready!r} {proc.stderr.read()!r}")
    return _Session(proc, sock_path, conn)

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
        s.conn.sendall((json.dumps({"id": rid, "code": code}) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.conn.recv(65536)
            if not chunk:
                _sessions.pop(session, None)
                return {"stdout": "", "stderr": "", "error": "R worker died",
                        "plots": [], "truncated": False, "degraded": False}
            buf += chunk
        return json.loads(buf.decode())
    except (BrokenPipeError, OSError) as e:
        _sessions.pop(session, None)
        return {"stdout": "", "stderr": "", "error": f"R worker died: {e}",
                "plots": [], "truncated": False, "degraded": False}


@mcp.tool()
def run_code(session: str, code: str, timeout: int = 300) -> RunResult:
    """Execute R code in a persistent REPL session. Variables, libraries, and
    loaded data persist across calls. Returns stdout, stderr, error, plots
    (saved-PNG paths), truncated/degraded. Auto-creates the session."""
    r = _call_worker(session, code)
    return RunResult(**{k: r.get(k) for k in RunResult.model_fields})

@mcp.tool()
def list_variables(session: str) -> VarList:
    """List R objects in the session (.GlobalEnv) with class/preview summaries."""
    r = _call_worker(session,
      "vapply(ls(envir=.GlobalEnv), function(nm) { o <- get(nm, envir=.GlobalEnv); "
      "list(name=nm, type=class(o)[1], size=paste(dim(o) %||% length(o), collapse='x'), "
      "preview=str(utils::head(o,1))[1], has_children=is.recursive(o) && length(o)>0) }, "
      "list(name='',type='',size='',preview='',has_children=FALSE))")
    # The R worker returns stdout = printed representation; for structured list,
    # have the worker emit JSON via cat(jsonlite::toJSON(...))
    # (Refine in Step 4 if the shape doesn't parse — see self-review.)
    import json as _j
    try:
        parsed = _j.loads(r["stdout"].strip().split("\n")[-1])
        return VarList(variables=[VarSummary(**v) for v in parsed])
    except Exception:
        return VarList(variables=[])

@mcp.tool()
def inspect_variable(session: str, name: str, path: list = None) -> InspectResult:
    """Inspect an R object (optionally drilling by path: [[...]]/element)."""
    code = f"str({name}); print(utils::head({name}, 10))"
    r = _call_worker(session, code)
    return InspectResult(name=name, repr=r.get("stdout",""), error=r.get("error"))

@mcp.tool()
def inject(session: str, path: str) -> Ack:
    """Source an R sidecar (kernel.R) into the session namespace."""
    r = _call_worker(session, f'source("{path}", local = .GlobalEnv)')
    return Ack(ok=r.get("error") is None, message=r.get("error") or f"injected {path}")

@mcp.tool()
def restart(session: str) -> Ack:
    """Kill + respawn the R worker — wipes .GlobalEnv. Use sparingly (loses state)."""
    s = _sessions.pop(session, None)
    if s:
        try: s.conn.close()
        except Exception: pass
        try: s.proc.terminate(); s.proc.wait(timeout=2)
        except Exception: pass
    return Ack(ok=True, message=f"restarted R session '{session}'")

@mcp.tool()
def session_info(session: str) -> SessionInfo:
    s = _sessions.get(session)
    running = s is not None and s.proc.poll() is None
    return SessionInfo(session=session, running=running,
                       pid=s.proc.pid if running else None, plot_dir=_common.plot_dir())

if __name__ == "__main__":
    mcp.run()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy pytest tests/test_r_server.py -v`
Expected: PASS (3 tests). If `list_variables` doesn't parse (the inline R is fiddly), revise the R expression so the worker emits `cat(jsonlite::toJSON(<list>))` and the server parses that — the goal is a structured list; the exact R expression is driven by the test.

- [ ] **Step 5: Commit**

```bash
git add data-science/interactive-repl/scripts/r_repl_server.py data-science/interactive-repl/tests/test_r_server.py
git commit -m "Add r_repl_server: MCPServer, session pool, Unix-socket proxy to repl.R"
```

---

### Task 11: Base `kernel.R` sidecar — `who`/`peek`/`fig` (auto-injected)

**Files:**
- Create: `data-science/interactive-repl/scripts/kernel.R`
- Modify: `data-science/interactive-repl/scripts/r_repl_server.py` (auto-source at start)
- Test: `data-science/interactive-repl/tests/test_r_kernel_sidecar.py`

- [ ] **Step 1: Write the failing test**

```python
# data-science/interactive-repl/tests/test_r_kernel_sidecar.py
import asyncio, sys, pathlib, pytest
HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parent / "scripts"))

@pytest.mark.asyncio
async def test_r_base_sidecar_loaded_at_start(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from r_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "rsc", "code": "who()"})
        assert r.structured_content["error"] is None  # who() exists, no "could not find function"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy pytest tests/test_r_kernel_sidecar.py -v`
Expected: FAIL (`who` not defined).

- [ ] **Step 3: Write `kernel.R` and auto-source it**

```r
# data-science/interactive-repl/scripts/kernel.R
# Base interactive-repl R sidecar — auto-sourced into every r-repl session.
# Definition-only, lazy deps — reference example for sidecar authoring.

who <- function() {
  ns <- ls(envir = .GlobalEnv)
  cls <- vapply(ns, function(nm) class(get(nm, envir = .GlobalEnv))[1], character(1))
  print(data.frame(object = ns, class = cls, row.names = NULL))
}

peek <- function(obj) {
  if (is.data.frame(obj)) {
    cat(sprintf("data.frame %s\n", paste(dim(obj), collapse = " x ")))
    print(str(obj)); print(head(obj))
  } else if (is.recursive(obj)) {
    cat(sprintf("%s len=%d\n", class(obj)[1], length(obj)))
    print(str(obj, max.level = 1))
  } else {
    print(obj)
  }
}

fig <- function(n = 1) {
  fs <- list.files(Sys.getenv("REPL_FIG_DIR", "/tmp"), pattern = "^fig.*\\.png$",
                   full.names = TRUE)
  fs <- sort(fs)
  if (length(fs) >= n) fs[n] else NULL
}
```

Auto-source at session start: in `r_repl_server.py`'s `_start`, after reading the ready marker, send a `source()` call for `kernel.R`:

```python
# in _start, after the ready-marker read:
kernel_r = HERE / "kernel.R"
if kernel_r.exists():
    s.conn.sendall((json.dumps({"id":"init","code": f'source("{kernel_r}", local=.GlobalEnv)'}) + "\n").encode())
    s.conn.recv(65536)  # discard init response
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy pytest tests/test_r_kernel_sidecar.py tests/test_r_server.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add data-science/interactive-repl/scripts/kernel.R data-science/interactive-repl/scripts/r_repl_server.py data-science/interactive-repl/tests/test_r_kernel_sidecar.py
git commit -m "Add base kernel.R sidecar (who/peek/fig), auto-source at R session start"
```

**Phase 2 complete:** working persistent R REPL, end-to-end. Both languages now live.

---

## Phase 3 — Ship

### Task 12: `SKILL.md` — frontmatter + behavioral guidance

**Files:**
- Create: `data-science/interactive-repl/SKILL.md`

- [ ] **Step 1: Write `SKILL.md`** (under 500 lines / 5k tokens; the body is §15 of the spec, condensed)

```markdown
---
name: interactive-repl
description: Open and drive a persistent R or Python REPL so you can iterate in-session
  — run code, inspect variables, fix assumptions, re-plot — without re-running scripts
  from scratch each time. Use this skill whenever the task involves iterating on data
  in R or Python (load → transform → inspect → plot → fix), "keep a session open",
  "run this chunk", "what's in this dataframe", or exploring/analyzing a dataset
  interactively. Triggers on pandas/tidyverse/ggplot/matplotlib work. Do NOT use for
  batch pipelines or long-running jobs — use the pipeline-maker skill there.
metadata:
  author: Altair Wei
  version: "0.1"
license: MIT
---

# Interactive REPL

A data scientist keeps one live session open per task — load data once, inspect,
fix assumptions, re-plot. Re-running a script from scratch each time you want to peek
wastes time and breaks the iterate-fast loop. This skill gives you a persistent
R/Python REPL via two MCP servers (`python-repl`, `r-repl`) so state survives across
calls.

## The iterate rule

Once a session is started for a task, keep running code **in it**. Don't re-run a
one-shot script to peek at a result — state persists, use it. Re-importing and
re-loading each turn wastes tokens and time.

## When to use the REPL — and when not

Use it for stateful, multi-chunk, state-carrying analysis — load once, iterate across
many calls sharing DB connections and loaded frames. **Don't force it for one-shot
extraction** — for exploratory SQL+regex text-mining, batch pipelines, or long-running
jobs (training, big joins), use one-shot scripts / the `pipeline-maker` skill.

You don't need to call `start` — the first `run_code` auto-creates the named session.
Pick a session name matching the task (`lmp`, `infection`, …) and keep using it.

## Language choice

Match the surrounding project (pandas vs tidyverse — see the `exploratory-data-analysis`
skill). Route to `python-repl` or `r-repl` accordingly.

## The tools (per server)

- `run_code(session, code)` — run code; returns `{stdout, stderr, error, plots:[path], truncated, degraded}`. State persists.
- `list_variables(session)` — variable summary (type/size/preview).
- `inspect_variable(session, name, path?)` — drill into a DataFrame's columns / a list's elements.
- `inject(session, path)` — exec a `kernel.py`/`kernel.R` sidecar into the namespace. Call once when another skill ships a sidecar.
- `restart(session)` — wipe + respawn the worker. **Rarely** — only after a crash or to deliberately reset (loses DB connections + loaded data).
- `session_info(session)` — versions, loaded packages, working dir, variable count.

## Plots — save and look (necessary, not sufficient)

`run_code` auto-saves figures (matplotlib → PNG; ggplot → `ggsave`) and returns paths.
**`Read` the PNG to actually see it.** But know you can `Read` a PNG and still
mis-reason: a real session attributed empty `scale_y_log10()` histogram panels to
"censored markers" when the true cause was `count=1` bars can't render 1→0 on log10
(`log(0)` undefined). Understand the **rendering semantics**, not just the data —
especially for log/tricky-scale plots. If the user says "the plot looks wrong," believe
them first, then look. Don't auto-"fix" because you saw a warning (`log(0)=-Inf` /
`Removed N rows` are normal). If `Read` returns "Unsupported Image," verify key
distribution stats numerically.

## R conventions

- Prefer `pkg::fun()` over `library()` (avoids attaching/clobbering).
- Prefer `scale_y_sqrt()` over `scale_y_log10()` to avoid the `count=1` down-fill artifact.
- Use absolute paths for `source()`/`read.csv()`/file args — the session's cwd may differ from yours.

## Multi-session discipline

One driver per session — don't interleave writes to the same named session from parallel
turns. Use distinct names for parallel tasks (`lmp`, `splitqc`, …). Session names are
scoped per server: a `lmp` session on `python-repl` and on `r-repl` are independent.

## When to restart (rarely)

After a crash (`run_code` returns "worker died") → `restart(session)`, or to deliberately
reset. **Do not restart between chunks "to be safe"** — restart-cycles lose DB
connections and loaded data.

## Ad-hoc inspection is first-class

`run_code` runs any code; use it freely for quick peeks (`_peek(df)`, `dim(df)`,
`head(df)`). For notebook/qmd workflows, extract a chunk's code (read the chunk body or
`knitr::purl`) and pass it to `run_code`.

## Survives compaction

REPL state lives in the server process, outside your context window. If your context is
compacted mid-analysis, re-attach by session name + `list_variables` and recover — the
DB connections and loaded data are still there.

## Extensibility

When another active skill ships a `kernel.py`/`kernel.R`, call `inject(path)` once
before using its helpers.

## Deep docs

Read on demand: `references/tools.md` (full API), `references/sidecar-authoring.md`
(how to write a sidecar for your skill), `references/r-setup.md` (conda env,
neutralized functions), `references/troubleshooting.md` (stuck code, missing deps,
worker crashes), `references/plot-iteration.md` (save-and-look, expanded).
```

- [ ] **Step 2: Verify size**

Run: `./count-skill-tokens.py data-science/interactive-repl`
Expected: under 500 lines / ~5k tokens; description under ~100 tokens. Trim the body if over.

- [ ] **Step 3: Commit**

```bash
git add data-science/interactive-repl/SKILL.md
git commit -m "Add interactive-repl SKILL.md (behavioral guidance, iterate rule)"
```

---

### Task 13: `references/*.md`

**Files:**
- Create: `data-science/interactive-repl/references/{tools,sidecar-authoring,r-setup,troubleshooting,plot-iteration}.md`

- [ ] **Step 1: Write each reference (condensed from the spec sections they expand)**

  - `tools.md`: the full tool signatures + return schemas (copy the §8 table + the Pydantic model fields from `python_repl_server.py`/`r_repl_server.py`).
  - `sidecar-authoring.md`: top-level definitions only, all non-stdlib imports inside function bodies, no side-effect code at load (passes an AST gate — the wisp-science convention). Show a minimal `kernel.py` example. Note: the agent calls `inject(path)` once; the sidecar's functions live in the session namespace.
  - `r-setup.md`: conda env (`INTERACTIVE_REPL_R_ENV`), `pkg::fun()` over `library()`, `scale_y_sqrt()` over `scale_y_log10()`, the `dt_table`→`kable` neutralization (and how to add more neutralizations), `knitr::purl` for chunk extraction.
  - `troubleshooting.md`: worker crash → `restart`; long code → chunk it (Claude Code's Bash timeout doesn't apply to `run_code`, but `run_code` has its own `timeout`); `browser()`/`readline()`/`scan()` blocks (avoid interactive R calls); missing `mcp`/`uv`/R → install; compaction → re-attach by session name.
  - `plot-iteration.md`: the save-and-look loop, the `scale_y_log10` `count=1` down-fill episode (from the spec), the "looking isn't sufficient — understand rendering semantics" lesson, the "Unsupported Image" → numerical fallback.

  Content: pull the relevant spec sections (§8, §11, §9/§14, §13, §15.5) and expand with the r-cell session evidence. Keep each under ~300 lines.

- [ ] **Step 2: Commit**

```bash
git add data-science/interactive-repl/references/
git commit -m "Add interactive-repl references (tools, sidecar authoring, R setup, troubleshooting, plot iteration)"
```

---

### Task 14: Marketplace + README — register the skill and its `mcpServers`

**Files:**
- Modify: `.claude-plugin/marketplace.json` (add skill to `data-science` + inline `mcpServers`)
- Modify: `README.md` (add skill to the data-science table; note the MCP-server convention)

- [ ] **Step 1: Update `marketplace.json`**

In the `data-science` plugin entry, add the skill and the `mcpServers` block (per spec §5):

```json
{
  "name": "data-science",
  "description": "Skills for data analysis, statistics, and visualization",
  "source": "./",
  "strict": false,
  "skills": [
    "./data-science/exploratory-data-analysis",
    "./data-science/interactive-repl"
  ],
  "mcpServers": {
    "python-repl": {
      "command": "uv",
      "args": ["run", "${CLAUDE_PLUGIN_ROOT}/data-science/interactive-repl/scripts/python_repl_server.py"]
    },
    "r-repl": {
      "command": "uv",
      "args": ["run", "${CLAUDE_PLUGIN_ROOT}/data-science/interactive-repl/scripts/r_repl_server.py"]
    }
  }
}
```

(Leave `bioinformatics` and `scientific-writing` untouched — no `mcpServers`.)

- [ ] **Step 2: Update `README.md`**

In the data-science table, add:

```markdown
| [interactive-repl](data-science/interactive-repl/) | Persistent R/Python REPL via two MCP servers (python-repl, r-repl) — iterate in-session instead of re-running scripts; auto plot capture, variable inspection, sidecar injection |
```

In the Repository-layout / Contributing section, add a note:

```markdown
The `interactive-repl` skill is the first to bundle MCP servers (inline `mcpServers`
on the `data-science` plugin entry). It is Claude-Code-specific; other skills remain
tool-agnostic.
```

- [ ] **Step 3: Verify JSON validity + skill token count**

Run: `python -c "import json; json.load(open('.claude-plugin/marketplace.json')); print('JSON valid')"` and `./count-skill-tokens.py data-science/interactive-repl`
Expected: JSON valid; token counts within limits.

- [ ] **Step 4: Commit**

```bash
git add .claude-plugin/marketplace.json README.md
git commit -m "Register interactive-repl in marketplace (data-science) + README; add inline mcpServers"
```

---

### Task 15: End-to-end smoke — install + trigger + round-trip in a fresh session

**Files:**
- Test: manual + `tests/test_smoke.py` (extend with R)

- [ ] **Step 1: Add the R stdio smoke test**

Mirror `test_smoke.py`'s `test_python_repl_stdio_roundtrip` for R — launch `r_repl_server.py` over stdio, call `run_code("1+1")`, assert `"2"` in stdout. Append to `tests/test_smoke.py`.

- [ ] **Step 2: Run the full test suite**

Run: `cd data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas pytest -v`
Expected: ALL tests pass.

- [ ] **Step 3: Manual install + trigger test**

```bash
cp -r data-science/interactive-repl ~/.claude/skills/
```

Start a fresh Claude Code session and try prompts that should trigger ("explore this CSV in R, keep a session open and iterate") and should not ("build me a Snakemake pipeline"). Iterate on `SKILL.md`'s `description` until triggering is reliable. (Per `CLAUDE.md` testing guidance.)

- [ ] **Step 4: Commit + final tag**

```bash
git add data-science/interactive-repl/tests/test_smoke.py
git commit -m "Add R stdio smoke test; Phase 3 complete"
git tag v0.1-interactive-repl
```

**Phase 3 complete:** the skill is shipped — `SKILL.md`, references, marketplace wiring, README, end-to-end smoke.

---

## Self-Review (run after writing the plan, before execution)

**1. Spec coverage** (§ by §):
- §2 MCP route + tool-agnostic departure → Tasks 4, 10, 14 (inline mcpServers; README note). ✓
- §4 identity/placement → Task 12 (SKILL.md `name`), Task 14 (marketplace path). ✓
- §5 packaging → Task 14. ✓
- §6 architecture (subprocess isolation) → Tasks 2, 4, 8, 10 (worker subprocess; server restarts on death). ✓
- §7 two servers + workers → Tasks 2–5 (Python), 8–10 (R). ✓
- §8 tool surface → Tasks 4–5 (run_code, session_info, restart, list_variables, inspect_variable, inject). ✓
- §9 worker patterns → Tasks 2–3 (Python: exec/eval, import hook, plot capture), 8–9 (R: withVisible, ggsave, tryCatch, neutralize). ✓
- §10 base sidecars → Tasks 6, 11. ✓
- §11 sidecar injection → Tasks 5, 6 (inject tool + auto-inject base). ✓
- §12 plot handling → Tasks 3, 9. ✓
- §13 error handling → Task 2/4 (tryCatch-guarantees-response, never-empty, worker-died→restart); dependency-ordering is covered by SKILL.md guidance (Task 12). ✓
- §14 configuration (`INTERACTIVE_REPL_*` env) → Task 10 (`r_repl_server._start` reads `INTERACTIVE_REPL_R_ENV`/`INTERACTIVE_REPL_R_BIN`). Python server defaults to `sys.executable`. ✓ (Note: `INTERACTIVE_REPL_PY_BIN` and `INTERACTIVE_REPL_TIMEOUT` not yet wired — add to `python_repl_server._start` and `run_code` during execution if needed.)
- §15 behavioral guidance → Task 12 (SKILL.md body). ✓
- §16 relationship to other skills → Task 12 (mentions EDA, pipeline-maker). ✓
- §17 testing → Tasks 1–11 (unit/integration), 15 (smoke + manual trigger). ✓
- §18 scope/v2 → not implemented (correctly deferred). ✓
- §19 risks → R Unix socket (Task 8), stdio crash recovery (Task 4 worker-died handling). ✓

**2. Placeholder scan:** "TBD"/"TODO" absent. The `list_variables` R expression (Task 10 Step 3) is fiddly and the plan says "Refine in Step 4 if the shape doesn't parse" — that's a genuine TDD iteration, not a placeholder; the test drives the final R expression.

**3. Type consistency:** `RunResult` fields match across `python_repl_server.py` (Task 4), `r_repl_server.py` (Task 10), and the SKILL.md doc (Task 12). `VarSummary` matches across both servers. `Ack`/`SessionInfo` consistent. `_common.py` symbols (`cap_output`, `never_empty`, `plot_dir`, `encode_line`, `decode_line`) used consistently in Tasks 2, 4, 10. ✓

No issues to fix inline. Plan is ready for execution.

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-05-interactive-repl.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Best for a plan this size; you stay in the loop without reading every code change.

**2. Inline Execution** — I execute tasks in this session using executing-plans, batching with checkpoints for your review.

**Which approach?**
