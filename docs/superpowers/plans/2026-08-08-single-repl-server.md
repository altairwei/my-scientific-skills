# Single `repl` Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate the two per-language MCP servers (`python-repl`, `r-repl`) into one `repl` server where language is a session-name attribute (`r:<name>` / `py:<name>`), per the approved spec `docs/superpowers/specs/2026-08-08-single-repl-server-design.md`.

**Architecture:** `repl_server.py` is born from `python_repl_server.py` (the shared glue: session pool, proxying, capping, slurm wiring, all 8 tools, `_call_worker`'s structured-error pattern). The 36% language-specific core moves into a `_LANGUAGES` registry keyed by session-name prefix: `"py"` (stdio JSON-lines + `python_worker.py`) and `"r"` (TCP localhost socket + conda-wrapped `R --no-save repl.R`). Session pool keys become the full prefixed names; `_parse_session` guards every tool with a structured ambiguity error. Workers, `repl.R`, sidecars, `discover.py`, `setup.sh`, `_slurm.py` are untouched.

**Tech Stack:** Python, mcp SDK v2 (`MCPServer`), pydantic, uv, pytest-asyncio, bash, R, Slurm (fake `srun`/`scancel`/`ssh` shims).

**Baseline facts** (verified):
- Tests load servers via `tests/conftest.py` (puts `scripts/` on sys.path), then `from <server> import mcp` + `async with Client(mcp) as client: client.call_tool(...)`.
- `python_repl_server.py` (414 lines): `mcp = MCPServer("python-repl")`; `_start` = slurm→`launch_remote([sys.executable, WORKER])` else stdio Popen + ready line; `_send`/`_recv` handle both `conn` (TCP) and `proc` pipes; `run_chunk` filters `c.language != _LANG` with hint `other = "r-repl" if _LANG == "python" else "python-repl"`; `restart` pops, scancels if job_id, closes conn or stdin, terminates.
- `r_repl_server.py` (391 lines): `mcp = MCPServer("r-repl")`; `_start` = `argv=[R_BIN, --no-save, --no-restore, -f, repl.R]` wrapped in `conda run -n <env> --no-capture-output` when `INTERACTIVE_REPL_R_ENV` set; local mode binds `127.0.0.1:0`, passes `REPL_PORT` env, `listen(1)` with 30 s accept timeout, reads ready line over the socket; `_LIST_VARS_R`; sidecar `kernel.R`.
- Models `VarList` and `SessionInfo` currently have NO error channel — they gain an additive optional `error: str | None = None` (call signatures unchanged; spec §4 "signatures unchanged" holds — the `session` argument is the only call input).
- `test_slurm.py` server-level tests import the servers at lines 170, 192, 220, 236, 256, 328, 352, 369, 385, 406, 422, 438; `test_smoke.py` imports both.
- Run tests from the skill dir with `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest <files> -v` (full suite is currently 131 passing).

---

### Task 1: `repl_server.py` skeleton — rename + `_parse_session` (pure unit)

**Files:**
- Create: `data-science/interactive-repl/tests/test_repl_server.py`
- Create: `data-science/interactive-repl/scripts/repl_server.py` (copy of `python_repl_server.py` with the deltas below)

- [ ] **Step 1: Write the failing tests**

`tests/test_repl_server.py`:

```python
import pytest


def test_import_smoke():
    from repl_server import mcp
    assert mcp is not None


def test_parse_session_known_prefixes():
    from repl_server import _parse_session
    assert _parse_session("r:lmp") == ("r", "lmp")
    assert _parse_session("py:lmp") == ("py", "lmp")
    assert _parse_session("py:abc:def") == ("py", "abc:def")  # bare may contain ':'
    assert _parse_session("r:") is None                       # empty bare name
    assert _parse_session("lmp") is None                      # no prefix
    assert _parse_session(":lmp") is None                     # empty prefix
    assert _parse_session("x:lmp") is None                    # unknown prefix
    assert _parse_session("python:lmp") is None               # 'python' is not 'py'
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_repl_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'repl_server'`.

- [ ] **Step 3: Create `repl_server.py` as a copy of the python server + deltas**

```bash
cp scripts/python_repl_server.py scripts/repl_server.py
```

Then apply exactly these edits:

(a) Header docstring (replace the current one):
```python
"""repl MCP stdio server. One server for both languages: the language lives in
the session name — 'r:<name>' spawns an R worker (repl.R), 'py:<name>' spawns
python_worker.py. Language-specific bits live in _LANGUAGES; everything else
is shared glue (session pool, proxying, capping, slurm)."""
```

(b) Import line: `import json, subprocess, sys, uuid` → `import json, os, socket, subprocess, sys, uuid` (os for R_ENV/R_BIN, socket for the R TCP launch — both used from Task 3 on; harmless before).

(c) Server name: `mcp = MCPServer("python-repl")` → `mcp = MCPServer("repl")`.

(d) After the `_sessions: dict[str, _Session] = {}` line, insert:
```python
# Session-name grammar: "<lang>:<name>" — language is a session attribute.
_LANGUAGE_PREFIXES = {"r", "py"}


def _parse_session(name: str):
    """'r:lmp' -> ('r', 'lmp'); 'py:lmp' -> ('py', 'lmp'); anything else -> None."""
    if ":" in name:
        lang, _, bare = name.partition(":")
        if lang in _LANGUAGE_PREFIXES and bare:
            return lang, bare
    return None
```

- [ ] **Step 4: Run to verify they pass**

Run: same command as Step 2. Expected: 2 passed. The old servers and their tests are untouched — full suite must stay green.

- [ ] **Step 5: Commit**

```bash
git add data-science/interactive-repl/scripts/repl_server.py data-science/interactive-repl/tests/test_repl_server.py
git commit -m "Add repl_server.py skeleton: MCPServer('repl') + session-name prefix parsing"
```

---

### Task 2: Session-language plumbing on the python path

**Files:**
- Modify: `scripts/repl_server.py`
- Modify: `tests/test_repl_server.py` (add ambiguity tests)
- Modify: `tests/test_python_server.py` (migrate to `repl_server` + `py:` prefixes)

- [ ] **Step 1: Write the failing ambiguity tests**

Append to `tests/test_repl_server.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_ambiguous_session_name_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "lmp", "code": "1+1"})
        sc = r.structured_content
        assert sc["error"] is not None
        assert "ambiguous" in sc["error"]
        assert "r:<name>" in sc["error"] and "py:<name>" in sc["error"]
        # no worker must have been spawned for an ambiguous name
        assert sc["stdout"] == ""


@pytest.mark.asyncio
async def test_unknown_prefix_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "x:lmp", "code": "1+1"})
        assert r.structured_content["error"] is not None


@pytest.mark.asyncio
async def test_ambiguous_name_all_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_chunk", {"session": "lmp", "file": "x.Rmd", "selector": "1"})
        assert r.structured_content["error"] is not None
        r = await client.call_tool("restart", {"session": "lmp"})
        assert r.structured_content["ok"] is False
        assert "ambiguous" in r.structured_content["message"]
        r = await client.call_tool("session_info", {"session": "lmp"})
        assert "ambiguous" in r.structured_content["error"]
        r = await client.call_tool("list_variables", {"session": "lmp"})
        assert "ambiguous" in r.structured_content["error"]
        r = await client.call_tool("inject", {"session": "lmp", "path": "/tmp/x.py"})
        assert r.structured_content["ok"] is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_repl_server.py -v`
Expected: the 3 new tests FAIL (ambiguity not yet wired — e.g. `run_code` with `"lmp"` starts a worker or errors differently).

- [ ] **Step 3: Wire the plumbing in `repl_server.py`**

(a) Rename the constant `_LIST_VARS_CODE` → `_LIST_VARS_PY` (used by `list_variables`).

(b) Replace `_base_sidecar_src()` with a language-aware version:
```python
def _base_sidecar_src(lang: str) -> str:
    """The base sidecar (kernel.py / kernel.R) — auto-injected at session start."""
    p = HERE / _LANGUAGES[lang]["sidecar"]
    return p.read_text() if p.exists() else ""
```

(c) Add the registry with ONLY the "py" entry (place it just above `_base_sidecar_src`). The "r" entry is added in Task 3 — its `_r_worker_cmd` / `_LIST_VARS_R` do not exist yet, and referencing them at module import would NameError:
```python
# The language-specific core, keyed by session-name prefix. Everything else in
# this file is shared glue (session pool, proxying, capping, slurm). The "r"
# entry is added in Task 3.
_LANGUAGES = {
    "py": {
        "cmd": lambda: [sys.executable, str(WORKER)],
        "tcp": False,                  # stdio JSON lines
        "list_vars": _LIST_VARS_PY,
        "sidecar": "kernel.py",
    },
}
```

(d) `_start` takes `(lang, bare)` and dispatches; pool key is the full prefixed name:
```python
def _start(lang: str, bare: str) -> _Session:
    spec = _LANGUAGES[lang]
    cmd = spec["cmd"]()
    if _slurm.slurm_enabled():
        proc, conn, meta = _slurm.launch_remote(cmd)
        s = _Session(proc, conn, meta["job_id"], meta["node"], meta["transport"])
    elif spec["tcp"]:
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
    else:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, bufsize=1)
        ready = json.loads(p.stdout.readline())
        if not ready.get("ready"):
            raise RuntimeError(f"worker failed to start: {ready!r} {p.stderr.read()!r}")
        s = _Session(p)
    # Auto-inject the base sidecar so _peek/_who/_fig are available immediately.
    base = _base_sidecar_src(lang)
    if base:
        _send(s, _common.encode_line({"id": "init", "code": base}))
        _recv(s)  # discard the init response
    return s


def _get(lang: str, bare: str) -> _Session:
    key = f"{lang}:{bare}"
    s = _sessions.get(key)
    if s is None or s.proc.poll() is not None:
        s = _start(lang, bare)
        _sessions[key] = s
    return s
```

(e) `_call_worker` parses the session name and returns the structured ambiguity error:
```python
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
```
(`_sessions.pop(session, None)` still works because pool keys are the full prefixed names.)

(f) `run_chunk`: parse at the top; replace the language filter. Old lines:
```python
        if c.language != _LANG:
            other = "r-repl" if _LANG == "python" else "python-repl"
            skipped.append(ChunkSkipped(index=c.index, label=c.label, language=c.language,
                                        reason=f"language={c.language}, use {other}"))
            continue
```
become:
```python
        if c.language != lang:
            other = "py" if lang == "r" else "r"
            skipped.append(ChunkSkipped(index=c.index, label=c.label, language=c.language,
                                        reason=f"language={c.language}, use {other}:<name>"))
            continue
```
and right after `def run_chunk(session: str, file: str, selector: str) -> RunChunkResult:` (before the `parse_notebook` try), insert:
```python
    parsed = _parse_session(session)
    if parsed is None:
        return RunChunkResult(stdout="", stderr="", error=_AMBIG)
    lang, bare = parsed
```

(g) `run_code`: replace the docstring with the generic one (both languages):
```python
    """Execute code in a persistent REPL session — R or Python. The session
    name carries the language: 'r:<name>' for R, 'py:<name>' for Python
    (auto-created on first call). Variables, imports, and loaded data persist
    across calls. Returns stdout, stderr, error (traceback or condition), plots
    (saved-PNG paths), and truncated/degraded flags.

    The `timeout` parameter is advisory in v1 — the worker blocks until the code
    returns; a stuck cell surfaces as a worker-died error (call `restart`)."""
```

(h) `list_variables`: parse; use the registry's per-language code; surface errors:
```python
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
```
Add the error field to the model (next to the existing fields):
```python
class VarList(BaseModel):
    variables: list[VarSummary]
    error: str | None = None
```

(i) `session_info`: parse; add error channel:
```python
class SessionInfo(BaseModel):
    session: str
    running: bool
    pid: int | None = None
    plot_dir: str = ""
    job_id: str | None = None
    node: str | None = None
    transport: str = "local"
    error: str | None = None
```
and at the top of `session_info`:
```python
    if _parse_session(session) is None:
        return SessionInfo(session=session, running=False, error=_AMBIG)
```

(j) `restart`: parse at the top:
```python
    if _parse_session(session) is None:
        return Ack(ok=False, message=_AMBIG)
```

(k) `inject` docstring: "Exec a kernel.py sidecar…" → "Exec a kernel.py / kernel.R sidecar into the session namespace — the extensibility mechanism for other skills. The sidecar should be top-level definitions only (lazy imports), no side-effect code at load." (body unchanged — the ambiguity error flows through `_call_worker` into `Ack.message`).

- [ ] **Step 4: Run the new tests**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_repl_server.py -v`
Expected: all 5 tests PASS.

- [ ] **Step 5: Migrate `tests/test_python_server.py` to the merged server**

Exact transformation:
```bash
cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl
sed -i 's/from python_repl_server import mcp/from repl_server import mcp/' tests/test_python_server.py
sed -i 's/"session": "t\([0-9]*\)"/"session": "py:t\1"/g' tests/test_python_server.py
```
Verify no unprefixed sessions remain:
```bash
grep -n '"session"' tests/test_python_server.py | grep -v 'py:t'   # must print nothing
```
(If any name doesn't match the `tN` pattern, prefix it manually — the rule is: every session in this file gets `py:`.)

- [ ] **Step 6: Run the migrated python suite**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_server.py tests/test_python_worker.py -v`
Expected: PASS. Also run the full suite — the R server and everything else must be untouched and green.

- [ ] **Step 7: Commit**

```bash
git add scripts/repl_server.py tests/test_repl_server.py tests/test_python_server.py
git commit -m "Wire session-language plumbing: pool keyed by prefixed names, ambiguity errors, run_chunk filter by session lang"
```

---

### Task 3: R language entry — TCP launch + conda wrapper

**Files:**
- Modify: `scripts/repl_server.py`
- Modify: `tests/test_repl_server.py` (add R roundtrip test)
- Modify: `tests/test_r_server.py` (migrate to `repl_server` + `r:` prefixes)

- [ ] **Step 1: Write the failing R roundtrip test**

Append to `tests/test_repl_server.py`:

```python
@pytest.mark.asyncio
async def test_r_session_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "r:s1", "code": "x <- 6; x * 7"})
        sc = r.structured_content
        assert sc["error"] is None, sc["error"]
        assert "42" in sc["stdout"]
        r = await client.call_tool("run_code", {"session": "r:s1", "code": "x + 1"})
        assert "7" in r.structured_content["stdout"]
```

- [ ] **Step 2: Run to verify it fails**

Run: `timeout 90 uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_repl_server.py::test_r_session_roundtrip -v`
Expected: FAIL — `KeyError: 'r'` from `_LANGUAGES` inside `_start` (registry has only "py" until this task). Note: an uncaught tool-handler exception HANGS the in-process client, so the run may not exit on its own — the `timeout 90` wrapper makes the hang a hard failure; treat timeout as the expected red.

- [ ] **Step 3: Add the R entry to `repl_server.py`**

(a) Add the path constant next to `WORKER`:
```python
REPL_R = HERE / "repl.R"
```

(b) Add `_r_worker_cmd` above the `_LANGUAGES` registry, and add the `_LIST_VARS_R` constant next to `_LIST_VARS_PY` (both verbatim from `r_repl_server.py`):
```python
def _r_worker_cmd() -> list:
    r_env = os.environ.get("INTERACTIVE_REPL_R_ENV")
    r_bin = os.environ.get("INTERACTIVE_REPL_R_BIN", "R")
    argv = [r_bin, "--no-save", "--no-restore", "-f", str(REPL_R)]
    return (["conda", "run", "-n", r_env, "--no-capture-output", *argv]
            if r_env else argv)
```
```python
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
```

(c) Add the "r" entry to the registry (the tcp branch of `_start` from Task 2 and the `os`/`socket` imports are already in place; `scripts/kernel.R` exists):
```python
_LANGUAGES = {
    "py": {
        "cmd": lambda: [sys.executable, str(WORKER)],
        "tcp": False,                  # stdio JSON lines
        "list_vars": _LIST_VARS_PY,
        "sidecar": "kernel.py",
    },
    "r": {
        "cmd": _r_worker_cmd,
        "tcp": True,                   # R base socketConnection is TCP-only
        "list_vars": _LIST_VARS_R,
        "sidecar": "kernel.R",
    },
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_repl_server.py::test_r_session_roundtrip -v`
Expected: PASS (R worker launches over the TCP path; this machine has R — verified in earlier sessions).

- [ ] **Step 5: Migrate `tests/test_r_server.py`**

Exact transformation:
```bash
cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl
sed -i 's/from r_repl_server import mcp/from repl_server import mcp/' tests/test_r_server.py
sed -i 's/"session": "\([^"]*\)"/"session": "r:\1"/g' tests/test_r_server.py
```
Verify:
```bash
grep -n '"session"' tests/test_r_server.py | grep -v 'r:'   # must print nothing
```

- [ ] **Step 6: Run the migrated R suite + full suite**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/ -v`
Expected: full suite green (131 + 5 new so far).

- [ ] **Step 7: Commit**

```bash
git add scripts/repl_server.py tests/test_repl_server.py tests/test_r_server.py
git commit -m "Add R language entry: TCP launch + conda wrapper, migrate r-server tests to repl_server"
```

---

### Task 4: Cross-language isolation + run_chunk routing

**Files:**
- Modify: `tests/test_repl_server.py` (no code changes expected — verify)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_repl_server.py`:

```python
@pytest.mark.asyncio
async def test_cross_language_sessions_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:sess", "code": "x = 10"})
        await client.call_tool("run_code", {"session": "r:sess", "code": "y <- 20"})
        r = await client.call_tool("run_code", {"session": "py:sess", "code": "print(x)"})
        assert "10" in r.structured_content["stdout"]
        r = await client.call_tool("run_code", {"session": "py:sess", "code": "print('y' in dir())"})
        assert "False" in r.structured_content["stdout"]


@pytest.mark.asyncio
async def test_run_chunk_r_session_skips_python_chunks(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    nb = tmp_path / "mix.Rmd"
    nb.write_text("""```{r}
x <- 1
```
```{python}
print('hi')
```
""")
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_chunk", {"session": "r:mix", "file": str(nb), "selector": "1"})
        sc = r.structured_content
        assert sc["error"] is None, sc["error"]
        assert len(sc["ran"]) == 1 and sc["ran"][0]["language"] == "r"
        assert any(s["language"] == "python" and "py:<name>" in s["reason"]
                   for s in sc["skipped"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_repl_server.py::test_cross_language_sessions_isolated tests/test_repl_server.py::test_run_chunk_r_session_skips_python_chunks -v`
Expected: FAIL — `run_chunk`'s hint says `use py:<name>` only if Task 2's filter edit is in place; isolation may already pass. Any failure is a real fix target.

- [ ] **Step 3: Fix what fails**

The filter and `_parse_session` from Task 2 are expected to already satisfy both tests. If `test_cross_language_sessions_isolated` fails, the pool key or `_get` is wrong — inspect `_get` (must key on `f"{lang}:{bare}"`). If the chunk test fails on the hint text, fix the `reason` string to exactly `f"language={c.language}, use {other}:<name>"`.

- [ ] **Step 4: Run to verify they pass**

Run: same command as Step 2. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_repl_server.py scripts/repl_server.py
git commit -m "Verify cross-language isolation and run_chunk routing by session language"
```

---

### Task 5: worker_mode + slurm server-level tests on the merged server

**Files:**
- Modify: `tests/test_slurm.py`
- Modify: `tests/test_smoke.py`
- (No production code expected — `worker_mode` and slurm wiring were copied into `repl_server.py` verbatim.)

- [ ] **Step 1: Migrate `tests/test_slurm.py` server-level tests**

Exact transformation:
```bash
cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl
sed -i 's/from python_repl_server import mcp/from repl_server import mcp/; s/from r_repl_server import mcp/from repl_server import mcp/' tests/test_slurm.py
```
Then, for each test that originally imported `r_repl_server` (import sites at lines 236, 256, 352, 438 — `test_slurm_r_*`, `test_tunnel_r_*`, `test_worker_mode_r_server_smoke`), prefix its session names with `r:`; for all others (python imports), prefix with `py:`. Do it per test function:
```bash
grep -n '"session"' tests/test_slurm.py
```
and edit each occurrence so the prefix matches the language that test exercises (R-code tests get `r:`, python-code tests get `py:`). Verify by running the file.

- [ ] **Step 2: Migrate `tests/test_smoke.py`**

Same rule: `python_repl_server`/`r_repl_server` → `repl_server`; sessions get `py:`/`r:` per the language each smoke test exercises.

- [ ] **Step 3: Run the migrated suites**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_slurm.py tests/test_smoke.py -v`
Expected: all PASS (the fake `srun`/`scancel`/`ssh` shims exercise `_start`'s slurm branch through the merged server; `_call_worker`'s structured-error handling for token mismatch etc. must still work — `_sessions.pop` keys are now prefixed names, which the shims' flow exercises end-to-end).

- [ ] **Step 4: Commit**

```bash
git add tests/test_slurm.py tests/test_smoke.py
git commit -m "Migrate slurm + smoke server-level tests to repl_server with prefixed sessions"
```

---

### Task 6: Delete old servers, marketplace entry, docs sweep

**Files:**
- Delete: `scripts/python_repl_server.py`, `scripts/r_repl_server.py`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `data-science/interactive-repl/SKILL.md`, `README.md`,
  `references/notebook-iteration.md`, `references/r-setup.md`,
  `references/tools.md`, `references/troubleshooting.md`
- Verify: `references/slurm-hpc.md` (0 mentions found — check anyway)

- [ ] **Step 1: Delete the old servers**

```bash
git rm scripts/python_repl_server.py scripts/r_repl_server.py
```

- [ ] **Step 2: Marketplace — one entry**

In `.claude-plugin/marketplace.json`, remove the `python-repl` and `r-repl` entries from the `data-science` plugin's `mcpServers` and add:
```json
"repl": {
  "command": "uv",
  "args": ["run", "${CLAUDE_PLUGIN_ROOT}/data-science/interactive-repl/scripts/repl_server.py"]
}
```
(Use the exact same `command`/`args` shape as the entries being removed; only the name and script path change.)

- [ ] **Step 3: SKILL.md sweep (7 mentions) + session-naming paragraph**

- Intro paragraph: replace "This skill gives you a persistent R/Python REPL via two MCP servers (`python-repl`, `r-repl`) so state survives across calls." with "This skill gives you a persistent R/Python REPL via one MCP server (`repl`); the language is bound per session by name — `r:<task>` for R, `py:<task>` for Python — so state survives across calls."
- Add a "## Session naming" paragraph after the "Language choice" section:
```markdown
## Session naming — the language lives in the name

Every session name carries its language as a prefix: `r:<task>` spawns an R
worker, `py:<task>` a Python worker (auto-created on the first `run_code`).
Unprefixed names are rejected with "ambiguous session name — use 'r:<name>' or
'py:<name>'". `r:lmp` and `py:lmp` are independent workers — you can run both
languages side by side; just use distinct prefixes.
```
- "Language choice" section: "Route to `python-repl` or `r-repl` accordingly. Session names are scoped per server: a `lmp` session on `python-repl` and on `r-repl` are independent." → "Route by session-name prefix (`r:` / `py:`) accordingly. Sessions with different prefixes are independent even when the bare name matches (`r:lmp` vs `py:lmp`)."
- "The tools (per server)" heading → "The tools (one server, both languages)"; the `run_code` bullet's "state persists" note stays; adjust any "per server" phrasing.
- Setup section: "probe once (`session_info` on a throwaway session …)" stays; step 5 "re-verify with `session_info` on both servers" → "re-verify with `session_info` on a `py:smoke` and an `r:smoke` session".
- Check every remaining `python-repl`/`r-repl`/`python_repl`/`r_repl` occurrence and rewrite to the merged naming.

- [ ] **Step 4: README + references sweep**

`README.md` (3 mentions), `references/notebook-iteration.md` (4), `references/r-setup.md` (3), `references/tools.md` (2), `references/troubleshooting.md` (1): same replacement rule — server names → `repl`; session examples get `r:`/`py:` prefixes; `slurm-hpc.md` verify no names remain. Verify:
```bash
cd /home/altairwei/src/my-scientific-skills
grep -rn "python-repl\|r-repl\|python_repl\|r_repl" --include="*.md" --include="*.json" | grep -v external/ || echo "clean"
```
Expected: "clean" (or only hits inside `external/`, which is gitignored).

- [ ] **Step 5: Skill size check**

Run: `./count-skill-tokens.py data-science/interactive-repl`
Expected: SKILL.md under 500 lines / 5,000 tokens; description under 100 tokens (must stay under — do not grow the description).

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Delete two-language servers; marketplace + SKILL.md + references to single repl server"
```

---

### Task 7: Full verification + push

- [ ] **Step 1: Full suite**

Run: `cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl && uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/ -v`
Expected: all PASS (131 original + ~8 new). Report the count.

- [ ] **Step 2: No stale references anywhere**

Run: `grep -rn "python-repl\|r-repl\|python_repl\|r_repl" /home/altairwei/src/my-scientific-skills --include="*.md" --include="*.json" --include="*.py" | grep -v external/`
Expected: no output.

- [ ] **Step 3: Real-run smoke on both languages**

Run both:
```bash
cd /home/altairwei/src/my-scientific-skills/data-science/interactive-repl
uv run scripts/repl_server.py --help 2>&1 | head -5 || true   # script loads (uv deps)
echo '1+1' | Rscript -e 'cat("R ok\n")'                       # R available
```
and a quick in-process sanity check via pytest of the two roundtrip tests above (already covered in Task 3/4 steps). Then run `./count-skill-tokens.py data-science/interactive-repl` once more.

- [ ] **Step 4: Commit + push**

```bash
git add -A && git commit -m "Final verification: full suite green on single repl server" || true
git push origin main
```

---

## Self-review notes

- **Spec coverage:** §4 (API) → Tasks 1–4; §5 (implementation) → Tasks 1–3; §6 (migration: delete/marketplace/tests/docs) → Tasks 5–6; §7 (trade-offs) → no code; §8 (out of scope) → respected: no tool-surface changes, no transport unification, no compat aliases.
- **Placeholder scan:** every step has concrete code or an exact mechanical transformation; the two "expected no code change" steps (Task 4 Step 3, Task 5) name the exact spot to look if a test fails instead of punting.
- **Type consistency:** `_parse_session` returns `tuple[str, str] | None` everywhere; `_get(lang, bare)` and `_call_worker(session, code)` (parses internally) are the two entry shapes; pool keys are always full prefixed names, so `_sessions.pop(session, None)` in `_call_worker`/`restart` stays correct; `_LANGUAGES[lang]["cmd"]()` is always called without args; `VarList.error` / `SessionInfo.error` are additive `str | None = None` fields used identically by both tools.
