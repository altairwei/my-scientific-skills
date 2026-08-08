# close(session) Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `close(session)` MCP tool that kills and evicts a session's worker — `restart` minus respawn — plus the SKILL.md "用完即弃" discipline and tools.md docs.

**Architecture:** Extract the kill sequence from `restart` into a shared `_kill(s) -> bool` helper (scancel → close transport → terminate+wait, each guarded). `close` = parse → pop from pool → `_kill` → Ack; it never spawns, is idempotent, and shares the `_AMBIG` rejection. Language-agnostic — one copy serves `r:` and `py:` sessions; slurm cleanup comes for free via `job_id`.

**Tech Stack:** Python MCP server (`repl_server.py`), pytest + pytest-asyncio with the in-process Client; fake srun/scancel shims for the slurm test.

**Spec:** `docs/superpowers/specs/2026-08-08-close-session-tool-design.md` (user-approved).

**Test command** (run from `data-science/interactive-repl/`):

```bash
uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest <files> -v
```

---

### Task 1: `_kill` helper + `close` tool + 6 tests (TDD)

**Files:**
- Modify: `data-science/interactive-repl/tests/test_python_server.py` (append 5 tests)
- Modify: `data-science/interactive-repl/tests/test_slurm.py` (append 1 test)
- Modify: `data-science/interactive-repl/scripts/repl_server.py` (`_kill` helper; `restart` refactored to use it; `close` tool after `restart`)

- [ ] **Step 1: Append the 5 python-side tests to `tests/test_python_server.py`**

```python
@pytest.mark.asyncio
async def test_close_kills_and_evicts(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp, _sessions
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:cl1", "code": "x = 1"})
        assert "py:cl1" in _sessions
        ack = await client.call_tool("close", {"session": "py:cl1"})
        assert ack.structured_content["ok"] is True
        assert "closed session" in ack.structured_content["message"]
        assert "py:cl1" not in _sessions
        info = await client.call_tool("session_info", {"session": "py:cl1"})
        assert info.structured_content["running"] is False
        assert info.structured_content["pid"] is None


@pytest.mark.asyncio
async def test_close_then_run_code_is_fresh_namespace(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:cl2", "code": "z = 99"})
        await client.call_tool("close", {"session": "py:cl2"})
        r = await client.call_tool("run_code", {"session": "py:cl2", "code": "z"})
        assert r.structured_content["error"] is not None  # NameError after close


@pytest.mark.asyncio
async def test_close_idempotent_never_started(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        ack = await client.call_tool("close", {"session": "py:ghost"})
        assert ack.structured_content["ok"] is True
        assert "no running session" in ack.structured_content["message"]
        info = await client.call_tool("session_info", {"session": "py:ghost"})
        assert info.structured_content["running"] is False


@pytest.mark.asyncio
async def test_close_ambiguous_name_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        ack = await client.call_tool("close", {"session": "lmp"})
        assert ack.structured_content["ok"] is False
        assert "ambiguous session name" in ack.structured_content["message"]


@pytest.mark.asyncio
async def test_close_does_not_affect_other_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:cl3", "code": "a = 1"})
        await client.call_tool("run_code", {"session": "py:cl4", "code": "b = 2"})
        await client.call_tool("close", {"session": "py:cl3"})
        r = await client.call_tool("run_code", {"session": "py:cl4", "code": "b"})
        assert r.structured_content["error"] is None
        assert "2" in r.structured_content["stdout"]
```

- [ ] **Step 2: Append the slurm close test to `tests/test_slurm.py`** (after `test_slurm_python_restart_scancels`, mirroring its shim setup)

```python
@pytest.mark.asyncio
async def test_slurm_python_close_scancels(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "-c 4")
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "127.0.0.1")
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
```

- [ ] **Step 3: Run the new tests and verify they FAIL** (red phase)

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_server.py tests/test_slurm.py -k close -v`
Expected: all 6 fail with a tool-not-found error for `close` (the in-process Client rejects an unregistered tool).

- [ ] **Step 4: Implement — `_kill` helper + `restart` refactor + `close` tool in `scripts/repl_server.py`**

Insert `_kill` right after `_call_worker` (before `_to_run_result`):

```python
def _kill(s: _Session) -> bool:
    """Teardown one session's worker: scancel (slurm), close the transport,
    terminate the process. Returns True if a live worker was killed."""
    if s.proc.poll() is not None:
        return False
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
    return True
```

Replace `restart`'s kill body with the shared helper (behavior unchanged — message stays the same):

```python
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
```

Add `close` immediately after `restart`:

```python
@mcp.tool()
def close(session: str) -> Ack:
    """Kill the named session's worker and release it — scancels the slurm
    allocation, closes the transport, terminates the process. Unlike restart,
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
```

- [ ] **Step 5: Run the full suite and verify ALL green** (existing restart tests prove the refactor is behavior-preserving)

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/ -v`
Expected: 148 passed (142 existing + 6 new), 0 failed.

- [ ] **Step 6: Commit**

```bash
git add data-science/interactive-repl/scripts/repl_server.py data-science/interactive-repl/tests/test_python_server.py data-science/interactive-repl/tests/test_slurm.py
git commit -m "feat: close(session) tool — kill and evict a session's worker"
```

---

### Task 2: Docs — SKILL.md discipline + tools.md

**Files:**
- Modify: `data-science/interactive-repl/SKILL.md` (tools list; "When to restart" → restart vs close; multi-session discipline)
- Modify: `data-science/interactive-repl/references/tools.md` (eight → nine tools; new `close` section)

- [ ] **Step 1: SKILL.md — add `close` to the tools list** (immediately after the `restart` line, line 104)

```markdown
- `close(session)` — kill the session's worker and release it (scancels the slurm allocation). Sessions are **not** auto-closed — call `close` when the task is done; the next `run_code` on the same name starts a fresh worker.
```

- [ ] **Step 2: SKILL.md — turn "When to restart (rarely)" into restart-vs-close guidance** (replace the section body, keep the heading style)

```markdown
## When to restart — and when to close

After a crash (`run_code` returns "worker died") → `restart(session)`, or to deliberately
reset. **Do not restart between chunks "to be safe"** — restart-cycles lose DB
connections and loaded data.

When the task is over (or you're moving to another project) → `close(session)`: kills
the worker and releases it — frees the process and, in slurm mode, the allocation.
Sessions are never auto-closed; a worker lives until closed or the server exits. The
next `run_code` on a closed name starts a fresh worker with an empty namespace.
```

- [ ] **Step 3: SKILL.md — append one line to "Multi-session discipline"** (after the `py:splitqc` example line)

```markdown
Close a session once its task is done — abandoned workers (and slurm allocations) stay alive until closed.
```

- [ ] **Step 4: tools.md — intro lists nine tools**

Change: `The \`repl\` server exposes eight tools (\`run_code\`, \`run_chunk\`, \`list_variables\`, \`inspect_variable\`, \`inject\`, \`restart\`, \`session_info\`, \`worker_mode\`)` → `The \`repl\` server exposes nine tools (\`run_code\`, \`run_chunk\`, \`list_variables\`, \`inspect_variable\`, \`inject\`, \`restart\`, \`close\`, \`session_info\`, \`worker_mode\`)`

- [ ] **Step 5: tools.md — add the `close` section after the `restart` section**

```markdown
## close(session) → Ack

```jsonc
{ "ok": true, "message": "closed session 'r:lmp'" }
```

Kill the named session's worker and release it — closes the transport, terminates the
process, and (slurm mode) scancels the allocation. Unlike `restart`, the worker is NOT
respawned; the next `run_code` on this name starts a fresh, empty session. Never creates
a session: closing a name that isn't running is a no-op success
(`{ "ok": true, "message": "no running session 'r:ghost'" }`). Sessions are not
auto-closed — call `close` when the task is done.
```

- [ ] **Step 6: Verify SKILL.md stays within limits**

Run (from repo root): `./count-skill-tokens.py data-science/interactive-repl`
Expected: SKILL.md under 500 lines / 5,000 tokens; description under 100 tokens (unchanged at 93).

- [ ] **Step 7: Commit**

```bash
git add data-science/interactive-repl/SKILL.md data-science/interactive-repl/references/tools.md
git commit -m "Docs: close(session) in SKILL.md and tools.md — 用完即弃 discipline"
```
