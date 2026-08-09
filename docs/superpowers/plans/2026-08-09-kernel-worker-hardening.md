# Kernel-Worker Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the proven hardening layer from `external/science-skills/kernel_worker.py` (interrupt discipline, write-time output caps, error attribution, usage metrics, fd/secret hygiene) into both REPL workers and the MCP server.

**Architecture:** Three coupled layers, executed worker-first so each commit stays green: (1) `python_worker.py` gains SIGINT discipline, `_CappedStringIO`, fd/secret hygiene, quitter shadow, attribution, usage; (2) `repl.R` gains the interrupt arm, guards, `interrupted`/`trace`/`usage` fields, secret unset, output cap; (3) `repl_server.py` gains the `interrupt` tool, a real `run_code` timeout (timeout → auto-interrupt → grace), a per-session busy lock, and the new `RunResult` fields. All interrupt behavior was empirically validated with probe scripts on 2026-08-09 (see spec §2).

**Tech Stack:** Python 3.10+ (mcp/pydantic server, stdlib-only worker), R 4.x, pytest + pytest-asyncio, fake srun/scancel/salloc shims for slurm tests.

**Test command (all tasks):**
```bash
cd data-science/interactive-repl
uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/<file> -q
```
Full suite: same command with `tests/ -q` (expect 144 → 170 tests after this plan).

**Scope note (two small spec-completions, flagged for review):**
1. R worker gets a post-hoc output cap (1 MB + marker, `truncated: true`) — the spec covers capping only for Python; R's `textConnection` grows unboundedly during a runaway loop and the interrupt tool is its backstop. This caps what is *sent*.
2. Python response `stderr` becomes capped too (today only stdout is capped — `raw_stderr` is passed through uncapped).

---

### Task 1: `_CappedStringIO` in python_worker.py

**Files:**
- Modify: `data-science/interactive-repl/scripts/python_worker.py` (imports line, new class, main-loop capture, response build)
- Test: `data-science/interactive-repl/tests/test_python_worker.py`

- [ ] **Step 1: Write the failing unit tests**

```python
def test_capped_stringio_caps_at_byte_boundary():
    import python_worker
    c = python_worker._CappedStringIO()
    c.write("x" * (python_worker._CappedStringIO.BUFFER_CAP + 1000))
    v = c.getvalue()
    assert len(v.encode("utf-8", "surrogatepass")) <= python_worker.MAX_OUTPUT
    assert "dropped" in v and "1000" in v
    assert c.truncated is True


def test_capped_stringio_utf8_boundary_trim():
    import python_worker
    c = python_worker._CappedStringIO()
    big = "中" * (python_worker._CappedStringIO.BUFFER_CAP + 10)  # 3 bytes/char
    c.write(big)
    v = c.getvalue()
    v.encode("utf-8")  # must not raise — no split surrogate pair
    assert c.truncated is True


def test_capped_stringio_write_contract_and_no_cap():
    import python_worker
    c = python_worker._CappedStringIO()
    assert c.write("hello") == 5          # io contract: code points written-or-consumed
    assert c.getvalue() == "hello"
    assert c.truncated is False
    # runaway loop style: repeated writes after the cap stay cheap, marker once
    c.write("x" * 2000000)
    assert c.truncated is True
    c.write("y" * 2000000)                # still cheap, no exception
    assert c.truncated is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_worker.py::test_capped_stringio_caps_at_byte_boundary -q`
Expected: FAIL — `AttributeError: module 'python_worker' has no attribute '_CappedStringIO'`

- [ ] **Step 3: Implement `_CappedStringIO` + capped capture**

In `python_worker.py` imports line, add `time` and `resource` (used in Task 4; harmless now):

```python
import builtins, io, json, os, shutil, signal, subprocess, sys, time, traceback, uuid, resource
```

After the `MAX_OUTPUT = 1024 * 1024` line, add the class (ported from the reference, simplified):

```python
class _CappedStringIO(io.StringIO):
    """StringIO with a write-time UTF-8 byte cap. A runaway print/logging loop
    otherwise grows the buffer unboundedly and can OOM the worker — the cap is
    enforced at write() time, not after the fact. getvalue() appends a marker
    reporting the REAL dropped count. Truncation never splits a UTF-8 sequence."""

    BUFFER_CAP = MAX_OUTPUT - 256  # headroom so marker + content fit under MAX_OUTPUT

    def __init__(self):
        super().__init__()
        self._buffered = 0
        self._dropped = 0

    def write(self, s):
        if self._buffered >= self.BUFFER_CAP:
            self._dropped += len(s.encode("utf-8", "surrogatepass"))
            return len(s)
        n = len(s.encode("utf-8", "surrogatepass"))
        remaining = self.BUFFER_CAP - self._buffered
        if n <= remaining:
            self._buffered += n
            return super().write(s)
        # Trim on a UTF-8 boundary: encode, slice bytes, decode.
        head = s.encode("utf-8", "surrogatepass")[:remaining].decode("utf-8", "ignore")
        self._buffered = self.BUFFER_CAP
        self._dropped = n - remaining
        super().write(head)
        return len(s)  # honour io.write contract (code points written-or-consumed)

    def getvalue(self):
        v = super().getvalue()
        if self._dropped:
            return v + (f"\n…(buffer capped at {self.BUFFER_CAP // 1024} KB; "
                        f"{self._dropped} further bytes dropped)\n")
        return v

    @property
    def truncated(self):
        return self._dropped > 0
```

In `main()`, replace the capture block:

```python
        out_cap, err_cap = _CappedStringIO(), _CappedStringIO()
```

and in the response build, replace the post-hoc capping with the capped objects (note: stderr becomes capped too — spec-completion #2):

```python
        raw_stdout = out_cap.getvalue()
        raw_stderr = err_cap.getvalue()
        stdout = raw_stdout
        truncated = out_cap.truncated or err_cap.truncated
        degraded = not raw_stdout.strip() and bool(raw_stderr.strip())
        if degraded:
            stdout = _common.never_empty(stdout, raw_stderr)
        protocol_out.write(_common.encode_line({
            "id": rid, "stdout": stdout, "stderr": raw_stderr, "error": error,
            "plots": plots, "truncated": truncated, "degraded": degraded}))
        protocol_out.flush()
```

(`_common.cap_output` becomes unused by the worker but stays in `_common.py` — server-side safety net.)

- [ ] **Step 4: Add a spawned-worker cap test**

```python
def test_runaway_print_capped_in_worker():
    p = _spawn()
    try:
        r = _call(p, "print('x' * 5000000); print('tail-marker')")
        assert r["truncated"] is True
        assert "tail-marker" in r["stdout"]          # first write(s) land, rest dropped
        assert "dropped" in r["stdout"]
        assert len(r["stdout"]) < 2 * 1024 * 1024    # bounded even though 5 MB printed
    finally:
        p.stdin.close(); p.terminate()
```

- [ ] **Step 5: Run the worker tests**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_worker.py -q`
Expected: all pass (13 existing + 4 new).

- [ ] **Step 6: Commit**

```bash
git add scripts/python_worker.py tests/test_python_worker.py
git commit -m "feat(py worker): write-time capped output buffer (_CappedStringIO)"
```

---

### Task 2: Secret stripping + fd non-inheritance + linecache eviction

**Files:**
- Modify: `data-science/interactive-repl/scripts/python_worker.py`
- Test: `data-science/interactive-repl/tests/test_python_worker.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_secret_env_stripped_in_worker(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-123")
    monkeypatch.setenv("GITHUB_TOKEN", "gh-secret")
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", "/tmp/x")  # must NOT be stripped
    p = _spawn()
    try:
        r = _call(p, "import os; print(os.environ.get('ANTHROPIC_API_KEY'), '|', "
                      "os.environ.get('GITHUB_TOKEN'), '|', os.environ.get('CLAUDE_PLUGIN_DATA'))")
        assert "None | None | /tmp/x" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_protocol_fds_not_inheritable():
    # Protocol fds are dup'd 3 and 4 (0/1 → devnull); user subprocesses must
    # not inherit them (else server EOF detection can hang).
    p = _spawn()
    try:
        r = _call(p, "import os; print([os.get_inheritable(3), os.get_inheritable(4)])")
        assert "[False, False]" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_linecache_bounded():
    p = _spawn()
    try:
        for i in range(130):
            _call(p, f"def f{i}(): pass")
        r = _call(p, "import linecache; print(len(linecache.cache))")
        assert int(r["stdout"].strip()) < 130  # eviction keeps only the last ~128
    finally:
        p.stdin.close(); p.terminate()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_worker.py::test_secret_env_stripped_in_worker tests/test_python_worker.py::test_protocol_fds_not_inheritable tests/test_python_worker.py::test_linecache_bounded -q`
Expected: FAIL — secret printed back, `[True, True]` inherited, cache ≥ 130.

- [ ] **Step 3: Implement**

At the top of `main()` (before the fd dup block), add the secret pop — inside `main()` so module import in tests has no side effects:

```python
    # User code must never see the host's API keys (prompt-injection exfil
    # surface). Pop a static denylist from the WORKER's env only — never the
    # server's. Vars the worker needs (CLAUDE_PLUGIN_DATA, INTERACTIVE_REPL_*,
    # PATH, conda env vars, SLURM_*) are not in the list.
    for _k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY",
               "OPENROUTER_API_KEY", "GITHUB_TOKEN", "HF_TOKEN",
               "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        os.environ.pop(_k, None)
```

In the protocol fd block, mark both fds non-inheritable:

```python
    protocol_in = os.fdopen(os.dup(0), "r", encoding="utf-8", errors="replace")
    protocol_out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.set_inheritable(protocol_in.fileno(), False)
    os.set_inheritable(protocol_out.fileno(), False)
```

After the linecache registration, evict the tag 128 behind:

```python
        _lc.cache[cell_tag] = (len(code), None, code.splitlines(True), cell_tag)
        _lc.cache.pop(f"<repl:{counter - 128}>", None)
```

- [ ] **Step 4: Run to verify they pass**

Run: the same three tests.
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/python_worker.py tests/test_python_worker.py
git commit -m "feat(py worker): strip secrets, non-inheritable protocol fds, bounded linecache"
```

---

### Task 3: `exit()`/`quit()` quitter shadow

**Files:**
- Modify: `data-science/interactive-repl/scripts/python_worker.py`
- Test: `data-science/interactive-repl/tests/test_python_worker.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_exit_shadowed_with_hint():
    p = _spawn()
    try:
        r = _call(p, "exit()")
        assert r["error"] is not None and "disabled" in r["error"]
        assert r["interrupted"] is False
        r2 = _call(p, "1 + 1")          # worker survives
        assert r2["error"] is None and "2" in r2["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_sys_exit_not_blamed_on_quitter():
    p = _spawn()
    try:
        r = _call(p, "import sys; sys.exit(3)")
        assert r["error"] is not None and "SystemExit" in r["error"]
        assert "disabled" not in r["error"]   # marker gate: not the shadow quitter
        r2 = _call(p, "1 + 1")
        assert r2["error"] is None
    finally:
        p.stdin.close(); p.terminate()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_worker.py::test_exit_shadowed_with_hint -q`
Expected: FAIL — today `exit()` raises SystemExit caught by `except BaseException`, error has no "disabled" hint. (test_sys_exit already passes in spirit but has no "interrupted" key — `r["interrupted"]` would KeyError; both will pass after implementation.)

- [ ] **Step 3: Implement**

In `main()`, after the namespace pre-population (after the `namespace.update({...})` line), add:

```python
    # Shadow site.Quitter: the real exit()/quit() close sys.stdin before raising
    # SystemExit, killing the protocol channel. This quitter raises without
    # touching stdin; the marker subclass gates the hint so a library sys.exit()
    # is not blamed on REPL muscle memory.
    class _ReplQuitterExit(SystemExit):
        pass
    _ReplQuitterExit.__name__ = "SystemExit"
    _ReplQuitterExit.__qualname__ = "SystemExit"

    class _ReplQuitter:
        def __repr__(self):
            return ("exit()/quit() is disabled here — close the session with "
                    "the `close(session)` tool.")
        def __call__(self, code=None):
            raise _ReplQuitterExit(code)

    _quitter = _ReplQuitter()
    namespace["exit"] = namespace["quit"] = _quitter
    builtins.exit = builtins.quit = _quitter
```

Rewrite the cell-execution block with a default `interrupted` flag, the
hint-gated except arm, and the `interrupted` response key — self-contained;
Task 4 later extends the same block (adds `trace`, `usage`, the SIGINT
bracket):

```python
        out_cap, err_cap = _CappedStringIO(), _CappedStringIO()
        error = None
        interrupted = False
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = out_cap, err_cap
            _execute_cell(code, cell_tag, namespace)
        except BaseException as e:
            interrupted = bool(getattr(e, "_repl_delivered", False))
            error = traceback.format_exc()
            if isinstance(e, _ReplQuitterExit):
                error += ("\n(exit()/quit() is disabled here — close the session "
                          "with the `close(session)` tool.)")
        finally:
            sys.stdout, sys.stderr = old_out, old_err
```

and add the key to the response build:

```python
        protocol_out.write(_common.encode_line({
            "id": rid, "stdout": stdout, "stderr": raw_stderr, "error": error,
            "plots": plots, "truncated": truncated, "degraded": degraded,
            "interrupted": interrupted}))
        protocol_out.flush()
```

(`getattr(e, "_repl_delivered", False)` always yields False until Task 4
installs the handler — correct placeholder semantics: the tests pass now and
the delivered-signal distinction activates in Task 4.)

- [ ] **Step 4: Run to verify they pass**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_worker.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/python_worker.py tests/test_python_worker.py
git commit -m "feat(py worker): shadow exit()/quit() with a safe hint"
```

---

### Task 4: SIGINT discipline + interrupted/trace/usage in python_worker

**Files:**
- Modify: `data-science/interactive-repl/scripts/python_worker.py`
- Test: `data-science/interactive-repl/tests/test_python_worker.py`

- [ ] **Step 1: Write the failing tests**

First add `import time` and `import signal` to the test file's import line.

```python
def test_sigint_interrupts_cell_keeps_worker(monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", "/tmp/x")
    p = _spawn()
    try:
        p.stdin.write(json.dumps({"id": "t", "code": "import time; time.sleep(30)"}) + "\n")
        p.stdin.flush()
        time.sleep(1.0)
        p.send_signal(signal.SIGINT)
        r = json.loads(p.stdout.readline())
        assert r["interrupted"] is True
        assert "KeyboardInterrupt" in r["error"]
        # namespace + worker survive
        r2 = _call(p, "1 + 1")
        assert r2["error"] is None and "2" in r2["stdout"]
        assert r2["interrupted"] is False
    finally:
        p.stdin.close(); p.terminate()


def test_sigint_while_idle_is_swallowed():
    p = _spawn()
    try:
        p.send_signal(signal.SIGINT)          # idle: blocked in readline
        time.sleep(0.3)
        r = _call(p, "1 + 1")
        assert r["error"] is None and "2" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_user_raised_keyboardinterrupt_is_not_interrupted():
    p = _spawn()
    try:
        r = _call(p, "raise KeyboardInterrupt")
        assert r["interrupted"] is False      # delivered-SIGINT marker distinguishes it
        assert "KeyboardInterrupt" in r["error"]
    finally:
        p.stdin.close(); p.terminate()


def test_error_attribution_trace():
    p = _spawn()
    try:
        r = _call(p, "d = {'a': 1}\nd['missing']")
        assert r["error"] is not None
        t = r["trace"]
        assert t["error_lineno"] == 2
        assert "d['missing']" in t["error_call"]
    finally:
        p.stdin.close(); p.terminate()


def test_usage_fields_present():
    p = _spawn()
    try:
        r = _call(p, "x = 0\nfor i in range(1000000): x += i")
        u = r["usage"]
        assert u["wall_s"] >= 0 and u["cpu_s"] >= 0
        assert u["peak_rss_kb"] > 0
    finally:
        p.stdin.close(); p.terminate()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_worker.py::test_sigint_interrupts_cell_keeps_worker tests/test_python_worker.py::test_error_attribution_trace -q`
Expected: FAIL — today the in-cell SIGINT survives (accidentally) but `interrupted` is absent (KeyError) and `trace` is absent; idle SIGINT hangs the worker.

- [ ] **Step 3: Implement**

Add the `signal` import if not already done (Task 1's import line includes it). In `main()`, before the loop, after the fd dup block, add the conditional handler (validated in probes PF1/PF2/PF3):

```python
    # Conditional SIGINT discipline: raise KeyboardInterrupt ONLY while user
    # code is executing (one-shot, self-clears); swallow the signal anywhere
    # else (idle readline, json handling, response write) so the worker loop
    # and namespace survive. The marker distinguishes a DELIVERED SIGINT from
    # a user-written `raise KeyboardInterrupt` (which is an ordinary error).
    _in_user_code = [False]
    _sigint_delivered = [False]

    def _sigint_handler(signum, frame):
        if _in_user_code[0]:
            _in_user_code[0] = False
            _sigint_delivered[0] = True
            ki = KeyboardInterrupt()
            ki._repl_delivered = True
            raise ki
    signal.signal(signal.SIGINT, _sigint_handler)
```

Rewrite the cell-execution block (this is the shape Task 3 left, plus the bracket):

```python
        out_cap, err_cap = _CappedStringIO(), _CappedStringIO()
        error = None
        interrupted = False
        trace = None
        old_out, old_err = sys.stdout, sys.stderr
        wall0 = time.perf_counter()
        cpu0 = _cpu_seconds()
        try:
            _in_user_code[0] = True
            sys.stdout, sys.stderr = out_cap, err_cap
            _execute_cell(code, cell_tag, namespace)
            _in_user_code[0] = False
        except BaseException as e:
            _in_user_code[0] = False
            interrupted = bool(getattr(e, "_repl_delivered", False))
            error = traceback.format_exc()
            if isinstance(e, _ReplQuitterExit):
                error += ("\n(exit()/quit() is disabled here — close the session "
                          "with the `close(session)` tool.)")
            if isinstance(e, SyntaxError):
                lineno = getattr(e, "lineno", None)
            else:
                lineno = _error_lineno(e, cell_tag)
            trace = {"error_lineno": lineno,
                     "error_call": _error_call(e, cell_tag, code)}
        finally:
            _in_user_code[0] = False
            sys.stdout, sys.stderr = old_out, old_err
```

Add the two helpers at module level (before `main()`), ported from the reference:

```python
def _cpu_seconds():
    """Total CPU time (user+sys) of this process and its reaped children."""
    s = resource.getrusage(resource.RUSAGE_SELF)
    c = resource.getrusage(resource.RUSAGE_CHILDREN)
    return s.ru_utime + s.ru_stime + c.ru_utime + c.ru_stime


def _peak_rss_kb():
    """Peak RSS in KB: /proc/self/status VmHWM (Linux), getrusage elsewhere
    (macOS ru_maxrss is bytes → /1024)."""
    try:
        with open("/proc/self/status") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1])
    except OSError:
        pass
    try:
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            maxrss //= 1024
        return maxrss
    except Exception:
        return 0


def _error_lineno(exc, cell_tag):
    """Line number of the deepest frame whose co_filename is the cell tag —
    distinguishes THIS cell's frames from functions defined in prior cells."""
    tb = getattr(exc, "__traceback__", None)
    lineno = None
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == cell_tag:
            lineno = tb.tb_lineno
        tb = tb.tb_next
    return lineno


def _error_call(exc, cell_tag, code):
    """Failing-expression text of the deepest cell frame, via PEP 657
    byte-precise column positions (Python 3.11+); ≤200 chars; None when
    positions are unavailable. Failure-safe: any hostile exception object
    classifies as None, never escapes."""
    try:
        tb = getattr(exc, "__traceback__", None)
        hit = None
        while tb is not None:
            if tb.tb_frame.f_code.co_filename == cell_tag:
                hit = tb
            tb = tb.tb_next
        if hit is None:
            return None
        import itertools
        pos = next(itertools.islice(hit.tb_frame.f_code.co_positions(),
                                    hit.tb_lasti // 2, None), None)
        if pos is None:
            return None
        lineno, end_lineno, col, end_col = pos
        if lineno is None or col is None or end_col is None:
            return None
        lines = code.split("\n")
        # PEP 657 cols are UTF-8 BYTE offsets — slice the encoded line
        raw = lines[lineno - 1].encode("utf-8")
        if end_lineno is not None and end_lineno != lineno:
            seg = raw[col:].decode("utf-8", "replace")
        else:
            seg = raw[col:end_col].decode("utf-8", "replace")
        seg = seg.strip()
        return seg[:200] if seg else None
    except BaseException:
        return None
```

In the response build, add the three keys and the usage computation:

```python
        usage = {
            "wall_s": round(time.perf_counter() - wall0, 3),
            "cpu_s": round(_cpu_seconds() - cpu0, 3),
            "peak_rss_kb": _peak_rss_kb(),
        }
        protocol_out.write(_common.encode_line({
            "id": rid, "stdout": stdout, "stderr": raw_stderr, "error": error,
            "plots": plots, "truncated": truncated, "degraded": degraded,
            "interrupted": interrupted, "trace": trace, "usage": usage}))
        protocol_out.flush()
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_worker.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/python_worker.py tests/test_python_worker.py
git commit -m "feat(py worker): SIGINT discipline, interrupted/trace/usage in responses"
```

---

### Task 5: R worker — interrupt arm, guards, attribution, usage, hygiene

**Files:**
- Modify: `data-science/interactive-repl/scripts/repl.R`
- Test: `data-science/interactive-repl/tests/test_r_worker.py`

- [ ] **Step 1: Write the failing tests**

First add `import time` and `import signal` to the test file's import line.

```python
def test_r_sigint_interrupts_cell_keeps_worker(monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", "/tmp/x")
    p = _spawn()
    try:
        p.stdin.write(json.dumps({"id": "t", "code": "Sys.sleep(30)"}) + "\n")
        p.stdin.flush()
        time.sleep(1.0)
        p.send_signal(signal.SIGINT)
        r = json.loads(p.stdout.readline())
        assert r["interrupted"] is True
        assert r["error"] == "interrupted"
        r2 = _call(p, "1 + 1")
        assert r2["error"] is None and "2" in r2["stdout"]
        assert r2["interrupted"] is False
    finally:
        p.stdin.close(); p.terminate()


def test_r_error_call_attribution():
    p = _spawn()
    try:
        r = _call(p, "f <- function() stop('boom'); f()")
        assert r["error"] is not None and "boom" in r["error"]
        assert r["trace"]["error_call"] == "f()"
    finally:
        p.stdin.close(); p.terminate()


def test_r_usage_fields():
    p = _spawn()
    try:
        r = _call(p, "x <- sum(1:1000000)")
        u = r["usage"]
        assert u["wall_s"] >= 0 and u["cpu_s"] >= 0
        assert u["peak_rss_kb"] > 0
    finally:
        p.stdin.close(); p.terminate()


def test_r_secret_env_stripped(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret-123")
    p = _spawn()
    try:
        r = _call(p, "cat(nzchar(Sys.getenv('ANTHROPIC_API_KEY')), '|', "
                      "Sys.getenv('CLAUDE_PLUGIN_DATA'))")
        assert "FALSE" in r["stdout"] and "/tmp/x" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_r_output_capped():
    p = _spawn()
    try:
        r = _call(p, "cat(paste(rep('x', 5000000), collapse='')); cat('TAIL\\n')")
        assert r["truncated"] is True
        assert "TAIL" not in r["stdout"]        # 5 MB in ONE expression → capped whole
        assert "capped" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()
```

(Note: `test_r_output_capped` asserts the whole 5 MB write is dropped and the marker appears — the per-response cap trims the assembled text, so TAIL is inside the 1 MB head unless the cap is smaller; with 5 MB single cat, `substr(out_text, 1, 1024*1024)` keeps the first 1 MB (all 'x'), so "TAIL" is gone and the marker appended. If the paste collapses to one string, `out_text` is that string + nothing else. Adjust the assertion to match implementation if the marker check differs — see Step 3.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_r_worker.py -q`
Expected: FAIL — `interrupted` KeyError; SIGINT kills the worker; no trace/usage; secret visible.

- [ ] **Step 3: Implement**

Header comment: no change needed. At the top of the script, after `.repl$con_in <- file("stdin", "r")`, add the secret unset:

```r
# User code must never see the host's API keys — strip the same static list
# the python worker uses (worker env only; the server's env is untouched).
for (.k in c("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY",
             "OPENROUTER_API_KEY", "GITHUB_TOKEN", "HF_TOKEN",
             "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")) {
  if (nzchar(Sys.getenv(.k))) Sys.unsetenv(.k)
}
rm(.k)
```

Add a peak-RSS helper next to `.repl$plot_dir`:

```r
.repl$peak_rss_kb <- function() {
  tryCatch({
    hit <- grep("^VmHWM:", readLines("/proc/self/status"), value = TRUE)
    if (length(hit)) as.integer(sub("^VmHWM:[[:space:]]*", "", hit[1])) else NA
  }, error = function(e) NA)
}
```

Rewrite `run_cell` (validated in probes FR1/FR3/FR4; `error="interrupted"` per spec §5.1):

```r
.repl$run_cell <- function(code) {
  out <- ""; plots <- character(0); warns <- character(0); interrupted <- FALSE
  error_call <- NULL
  wall0 <- as.numeric(Sys.time()); cpu0 <- sum(proc.time()[1:2])
  stdout_con <- textConnection("out", "w", local = TRUE)
  sink(stdout_con, type = "output")
  error_msg <- tryCatch({
    ex <- parse(text = code)
    for (i in seq_along(ex)) {
      r <- withCallingHandlers(
        withVisible(eval(ex[[i]], envir = globalenv())),
        warning = function(w) {
          warns <<- c(warns, conditionMessage(w))
          invokeRestart("muffleWarning")
        }
      )
      if (isTRUE(r$visible)) {
        if (inherits(r$value, "ggplot")) {
          f <- tempfile(pattern = "fig-", fileext = ".png", tmpdir = .repl$plot_dir())
          tryCatch(ggplot2::ggsave(f, r$value, width = 12, height = 8, dpi = 110),
                   error = function(e) NULL)
          plots <- c(plots, f)
          cat("FIGURE saved:", f, "\n")
        } else {
          print(r$value)
        }
      }
    }
    NULL
  }, interrupt = function(e) {
    interrupted <<- TRUE
    NULL
  }, error = function(e) {
    ec <- tryCatch(deparse(conditionCall(e)), error = function(e2) NULL)
    if (!is.null(ec) && length(ec) > 0) error_call <<- paste(ec, collapse = " ")
    conditionMessage(e)
  })
  sink(); close(stdout_con)
  out_text <- paste(out, collapse = "\n")  # character(0) → "" (nzchar-safe)
  if (interrupted && is.null(error_msg)) error_msg <- "interrupted"
  if (!nzchar(out_text) && !is.null(error_msg)) out_text <- paste0("ERROR: ", error_msg)
  capped <- FALSE
  if (nchar(out_text, type = "bytes") > 1024 * 1024) {
    out_text <- paste0(substr(out_text, 1, 1024 * 1024),
                       "\n...(output capped at 1 MB; further bytes dropped)\n")
    capped <- TRUE
  }
  list(stdout = out_text, stderr = paste(warns, collapse = "\n"),
       error = error_msg, interrupted = interrupted,
       trace = if (is.null(error_call)) NULL else list(error_call = error_call),
       usage = list(wall_s = round(as.numeric(Sys.time()) - wall0, 3),
                    cpu_s = round(sum(proc.time()[1:2]) - cpu0, 3),
                    peak_rss_kb = .repl$peak_rss_kb()),
       plots = as.list(plots), truncated = capped, degraded = FALSE)
}
```

In `run_loop`, add the interrupt arm to the readLines tryCatch and wrap the response write (validated FR1; belt-and-suspenders per spec §5.2–5.3):

```r
    line <- tryCatch(readLines(.repl$con_in, n = 1),
                     interrupt = function(e) "",  # signal while idle: keep looping
                     error = function(e) character(0),
                     warning = function(w) character(0))
```

```r
    res$id <- rid
    # A SIGINT in the response-write window must not kill the loop — swallow
    # it (the response may be lost; the server's read timeout covers that).
    tryCatch(.repl$write_json(res), interrupt = function(e) NULL)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_r_worker.py -q`
Expected: all pass (6 existing + 5 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/repl.R tests/test_r_worker.py
git commit -m "feat(r worker): interrupt arm, interrupted/trace/usage, secret strip, output cap"
```

---

### Task 6: Server — busy lock, real timeout, auto-interrupt, RunResult fields

**Files:**
- Modify: `data-science/interactive-repl/scripts/repl_server.py`
- Test: `data-science/interactive-repl/tests/test_python_server.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_run_code_timeout_auto_interrupts(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    import time
    async with Client(mcp) as client:
        t0 = time.monotonic()
        r = await client.call_tool("run_code",
                                   {"session": "py:tmo1", "code": "import time; time.sleep(30)",
                                    "timeout": 1})
        sc = r.structured_content
        assert time.monotonic() - t0 < 15          # did NOT wait for the 30 s sleep
        assert sc["interrupted"] is True
        assert "KeyboardInterrupt" in (sc["error"] or "")
        # worker survived the auto-interrupt
        r2 = await client.call_tool("run_code", {"session": "py:tmo1", "code": "1 + 1"})
        assert r2.structured_content["error"] is None


def test_run_code_timeout_unresponsive_reports_restart(monkeypatch, tmp_path):
    """A cell that ignores SIGINT (SIG_IGN replaces the worker's handler) →
    'cell unresponsive' after interrupt + grace, worker NOT killed."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code",
                                   {"session": "py:tmo2",
                                    "code": "import signal, time; signal.signal(signal.SIGINT, signal.SIG_IGN); time.sleep(30)",
                                    "timeout": 1})
        sc = r.structured_content
        assert "unresponsive" in (sc["error"] or "")
        # worker still alive (not killed by the server) and the cell keeps running
        si = (await client.call_tool("session_info", {"session": "py:tmo2"})).structured_content
        assert si["running"] is True


def test_run_code_fields_interrupted_trace_usage(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code",
                                   {"session": "py:tr1", "code": "d = {'a': 1}\nd['missing']"})
        sc = r.structured_content
        assert sc["interrupted"] is False
        assert sc["trace"]["error_lineno"] == 2
        assert "d['missing']" in sc["trace"]["error_call"]
        assert sc["usage"]["wall_s"] >= 0
        assert sc["usage"]["peak_rss_kb"] > 0
```

(The unresponsive test takes ~11 s — 1 s timeout + 10 s grace. The SIG_IGN cell
keeps running after the test; the worker exits on stdin EOF at test end.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_server.py::test_run_code_timeout_auto_interrupts tests/test_python_server.py::test_run_code_fields_interrupted_trace_usage -q`
Expected: FAIL — KeyError `interrupted` / `trace` / `usage`; timeout param ignored (call hangs).

- [ ] **Step 3: Implement**

Imports: add `signal` and `threading` to the import line:

```python
import json, os, selectors, signal, subprocess, sys, threading, time, uuid
```

`_Session` gains a per-session lock:

```python
    def __init__(self, proc, job_id=None, node=None):
        self.proc = proc
        self.job_id = job_id
        self.node = node
        self.lock = threading.Lock()
```

New models after `RunResult`:

```python
class TraceInfo(BaseModel):
    error_lineno: int | None = None
    error_call: str | None = None


class UsageInfo(BaseModel):
    wall_s: float = 0.0
    cpu_s: float = 0.0
    peak_rss_kb: int = 0


class InterruptAck(BaseModel):
    ok: bool
    interrupted: bool = False
    message: str = ""
```

`RunResult` gains the fields:

```python
class RunResult(BaseModel):
    stdout: str
    stderr: str
    error: str | None = None
    plots: list[str] = Field(default_factory=list)
    truncated: bool = False
    degraded: bool = False
    interrupted: bool = False
    trace: TraceInfo | None = None
    usage: UsageInfo | None = None
```

Replace `_recv` with a deadline-aware chunked reader. CRITICAL: do NOT use
`select` + `readline()` — the BufferedReader's read-ahead can hold a complete
response while the fd shows no data, and a false timeout would auto-interrupt
an idle worker (killing the R one, per probes). Use `os.read` chunks like
`_read_ready` does — the buffer is per-call and the busy lock serializes reads
per session, so no state leaks between calls:

```python
def _recv(s: _Session, rid: str, timeout: float | None = None) -> dict:
    """Read one response line whose id matches rid, skipping any non-JSON
    garbage (R child-process output leaking onto stdout). With timeout=None,
    blocks until the response (worker death → OSError). With a timeout, raises
    TimeoutError when no matching line arrives in time."""
    sel = selectors.DefaultSelector()
    sel.register(s.proc.stdout, selectors.EVENT_READ)
    deadline = None if timeout is None else time.monotonic() + timeout
    buf = ""
    for _ in range(10000):  # sanity cap — a garbage flood shouldn't loop forever
        while "\n" not in buf:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not sel.select(remaining):
                    raise TimeoutError("no response within timeout")
            chunk = os.read(s.proc.stdout.fileno(), 65536)
            if not chunk:
                raise OSError("pipe closed")
            buf += chunk.decode(errors="replace")
        line, buf = buf.split("\n", 1)
        try:
            obj = json.loads(line.strip())
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and obj.get("id") == rid:
            return obj
    raise OSError("too much non-protocol output")
```

Add the interrupt-signalling helper next to `_kill`:

```python
_GRACE = 10  # seconds to wait for a response after an auto-interrupt


def _interrupt_proc(s: _Session) -> tuple[bool, str]:
    """Interrupt the running cell: SIGINT to the worker (local) or
    scancel --signal=INT on the job (slurm — salloc/srun local signal
    forwarding is unreliable). Returns (ok, message)."""
    if s.proc.poll() is not None:
        return False, "worker not running"
    if s.job_id:
        try:
            subprocess.run(["scancel", "--signal=INT", s.job_id], timeout=10,
                           capture_output=True)
            return True, f"sent SIGINT to slurm job {s.job_id}"
        except Exception as e:
            return False, f"scancel failed: {e}"
    try:
        os.kill(s.proc.pid, signal.SIGINT)
        return True, f"sent SIGINT to worker pid {s.proc.pid}"
    except OSError as e:
        return False, f"signal failed: {e}"
```

Rewrite `_call_worker` — busy lock, deadline, auto-interrupt, grace:

```python
def _call_worker(session: str, code: str, timeout: float | None = None) -> dict:
    parsed = _parse_session(session)
    if parsed is None:
        return {"stdout": "", "stderr": "", "error": _AMBIG,
                "plots": [], "truncated": False, "degraded": False}
    lang, bare = parsed
    rid = uuid.uuid4().hex
    try:
        s = _get(lang, bare)
        if not s.lock.acquire(blocking=False):
            return {"stdout": "", "stderr": "",
                    "error": f"session {lang}:{bare} is busy running a cell — "
                             f"wait for it to finish or call interrupt(session)",
                    "plots": [], "truncated": False, "degraded": False}
        try:
            _send(s, _common.encode_line({"id": rid, "code": code}))
            try:
                return _recv(s, rid, timeout)
            except TimeoutError:
                _interrupt_proc(s)  # auto-interrupt once; the worker survives
                try:
                    return _recv(s, rid, _GRACE)
                except TimeoutError:
                    return {"stdout": "", "stderr": "",
                            "error": "cell unresponsive after interrupt — "
                                     "call restart(session)",
                            "plots": [], "truncated": False, "degraded": False}
        finally:
            s.lock.release()
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
```

`_to_run_result` maps the new fields:

```python
def _to_run_result(r: dict) -> RunResult:
    return RunResult(
        stdout=r.get("stdout", ""),
        stderr=r.get("stderr", ""),
        error=r.get("error"),
        plots=r.get("plots") or [],
        truncated=r.get("truncated", False),
        degraded=r.get("degraded", False),
        interrupted=r.get("interrupted", False),
        trace=TraceInfo(**r["trace"]) if r.get("trace") else None,
        usage=UsageInfo(**r["usage"]) if r.get("usage") else None,
    )
```

`run_code` passes the timeout through and the docstring loses "advisory in v1":

```python
@mcp.tool()
def run_code(session: str, code: str, timeout: int = 300) -> RunResult:
    """Execute code in a persistent REPL session — R or Python. The session
    name carries the language: 'r:<name>' for R, 'py:<name>' for Python
    (auto-created on first call). Variables, imports, and loaded data persist
    across calls. Returns stdout, stderr, error (traceback or condition), plots
    (saved-PNG paths), truncated/degraded flags, interrupted (a delivered
    SIGINT), trace (error line + failing expression), and usage (wall/cpu/peak
    RSS).

    The `timeout` bounds the call: on expiry the server interrupts the cell
    once (the worker survives, `interrupted=true`), waits a grace period, and
    only reports 'cell unresponsive' if the cell ignores SIGINT. A busy
    session returns 'session busy' instead of interleaving on the pipe."""
    return _to_run_result(_call_worker(session, code, timeout=timeout))
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_server.py -q`
Expected: all pass. (The unresponsive test may take ~11 s — interrupt + 10 s grace. If `run_code` on a busy session is called from the same event loop while another call blocks a thread, the busy-rejection tests in Task 7 cover the lock; keep this task's tests to the three above.)

- [ ] **Step 5: Commit**

```bash
git add scripts/repl_server.py tests/test_python_server.py
git commit -m "feat(server): real run_code timeout (auto-interrupt + grace), busy lock, result fields"
```

---

### Task 7: Server — `interrupt` tool (local + slurm)

**Files:**
- Modify: `data-science/interactive-repl/scripts/repl_server.py`
- Test: `data-science/interactive-repl/tests/test_python_server.py`, `data-science/interactive-repl/tests/test_slurm.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_interrupt_tool_cancels_running_cell(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    import asyncio, time
    async with Client(mcp) as client:
        task = asyncio.create_task(
            client.call_tool("run_code", {"session": "py:int1", "code": "import time; time.sleep(30)"}))
        await asyncio.sleep(0.8)                 # let the cell start
        ack = await client.call_tool("interrupt", {"session": "py:int1"})
        sc = ack.structured_content
        assert sc["ok"] is True and sc["interrupted"] is True
        r = await task
        assert r.structured_content["interrupted"] is True
        r2 = await client.call_tool("run_code", {"session": "py:int1", "code": "1 + 1"})
        assert r2.structured_content["error"] is None   # worker survived


def test_interrupt_idle_session_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        ack = (await client.call_tool("interrupt", {"session": "py:int2"})).structured_content
        assert ack["ok"] is False
        assert "no cell running" in ack["message"] or "not running" in ack["message"]


def test_busy_session_rejects_second_call(monkeypatch, tmp_path):
    """A second run_code on a session with a cell in flight returns 'session
    busy' instead of interleaving on the pipe."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    import asyncio
    async with Client(mcp) as client:
        task = asyncio.create_task(
            client.call_tool("run_code", {"session": "py:busy1", "code": "import time; time.sleep(5)"}))
        await asyncio.sleep(0.8)
        r = await client.call_tool("run_code", {"session": "py:busy1", "code": "1 + 1"})
        assert "busy" in (r.structured_content["error"] or "")
        await client.call_tool("interrupt", {"session": "py:busy1"})
        await task
```

And in `tests/test_slurm.py`:

```python
@pytest.mark.asyncio
async def test_slurm_interrupt_scancels_signal(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "-c 4")
    _install_shims(tmp_path, monkeypatch)
    from mcp import Client
    from repl_server import mcp
    import asyncio
    async with Client(mcp) as client:
        task = asyncio.create_task(
            client.call_tool("run_code", {"session": "py:sint1", "code": "import time; time.sleep(30)"}))
        await asyncio.sleep(0.8)
        ack = await client.call_tool("interrupt", {"session": "py:sint1"})
        assert ack.structured_content["ok"] is True
        assert "--signal=INT 4242" in (tmp_path / "scancel.log").read_text()
        task.cancel()
        await asyncio.sleep(0)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_server.py::test_interrupt_tool_cancels_running_cell tests/test_slurm.py::test_slurm_interrupt_scancels_signal -q`
Expected: FAIL — `ToolNotFoundError: Unknown tool: interrupt`.

- [ ] **Step 3: Implement**

Add the tool after `close`:

```python
@mcp.tool()
def interrupt(session: str) -> InterruptAck:
    """Interrupt the cell currently running in the session — the worker
    survives with its namespace (the response arrives as interrupted=true).
    Local sessions: SIGINT to the worker process. Slurm sessions:
    scancel --signal=INT on the job (job id from the ready handshake).
    Rejected with ok=false when no cell is running (the server never signals
    an idle worker — R cannot survive that) or the session is gone."""
    parsed = _parse_session(session)
    if parsed is None:
        return InterruptAck(ok=False, message=_AMBIG)
    lang, bare = parsed
    s = _sessions.get(f"{lang}:{bare}")
    if s is None or s.proc.poll() is not None:
        return InterruptAck(ok=False, message=f"session '{session}' is not running")
    if not s.lock.locked():
        return InterruptAck(ok=False, message="no cell running in this session")
    ok, msg = _interrupt_proc(s)
    return InterruptAck(ok=ok, interrupted=ok, message=msg)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/test_python_server.py tests/test_slurm.py -q`
Expected: all pass (20 + 18 existing + 4 new).

- [ ] **Step 5: Commit**

```bash
git add scripts/repl_server.py tests/test_python_server.py tests/test_slurm.py
git commit -m "feat(server): interrupt(session) tool — SIGINT local, scancel --signal slurm"
```

---

### Task 8: Docs — interrupt-first workflow

**Files:**
- Modify: `data-science/interactive-repl/SKILL.md`, `data-science/interactive-repl/references/tools.md`, `data-science/interactive-repl/references/troubleshooting.md`, `data-science/interactive-repl/references/slurm-hpc.md`

- [ ] **Step 1: SKILL.md** — add `interrupt(session)` to the tools list (after `close`):

```markdown
- `interrupt(session)` — cancel the running cell; the worker and its state survive (`interrupted=true` in the result). Local: SIGINT; slurm: scancel `--signal=INT`. Use it when a cell runs long or seems stuck — check the partial output, then continue or `restart` only if the worker is unresponsive.
```

Update the "When to restart — and when to close" section: between the crash sentence and the restart sentence, insert:

```markdown
**Stuck cell? Interrupt first.** A cell that runs long or hangs is NOT a crash —
call `interrupt(session)` to cancel it (partial output, state intact), then
continue. `restart` is only for an unresponsive worker ("cell unresponsive
after interrupt" — the cell ignored SIGINT) or a deliberate reset. `run_code`
now enforces its `timeout` by interrupting the cell once before reporting
unresponsive.
```

- [ ] **Step 2: `references/tools.md`** — add the `interrupt` section (after the `close` section):

```markdown
## interrupt(session)

Cancel the cell currently running in the session. The worker and its namespace
survive — the in-flight `run_code` returns with `interrupted: true` and any
partial output. Local sessions: SIGINT to the worker; slurm sessions:
`scancel --signal=INT <job_id>`. Returns `{ok, interrupted, message}`.

- Rejected with `ok=false` when no cell is running — the server never signals
  an idle worker (the R worker cannot survive a signal delivered while idle).
- A cell that ignores SIGINT (e.g. `signal.SIG_IGN` or C-level work) surfaces
  as "cell unresponsive after interrupt" after a grace period — `restart`
  then.
- `run_code`'s `timeout` (default 300 s) is now enforced: on expiry the server
  auto-interrupts once, waits a grace period, then reports unresponsive.
- A second `run_code` on a session with a cell in flight returns "session
  busy" — wait or interrupt instead of piling on.
```

- [ ] **Step 3: `references/troubleshooting.md`** — replace the "Long-running code" section body:

```markdown
## Long-running code / stuck cells

`run_code` has a real `timeout` (default 300s): on expiry the server
interrupts the cell once — the worker survives, the result returns with
`interrupted: true` and partial stdout. If the cell ignores SIGINT you get
"cell unresponsive after interrupt" → then `restart`. Claude Code's Bash
timeout does **not** apply to MCP tool calls. Very long jobs (training, big
joins) are not what the REPL is for — use one-shot scripts /
`pipeline-maker`. If a cell runs away, call `interrupt(session)` yourself
instead of waiting for the timeout.
```

- [ ] **Step 4: `references/slurm-hpc.md`** — in the Semantics section, after the restart/close bullet, add:

```markdown
- **`interrupt`** sends `scancel --signal=INT <job_id>` — the cell on the
  compute node is cancelled, the allocation and namespace survive. (Local
  SIGINT to the salloc chain is unreliable — the job id from the ready
  handshake is the robust path.)
```

- [ ] **Step 5: Verify token budget**

Run: `./count-skill-tokens.py data-science/interactive-repl`
Expected: SKILL.md still under 500 lines / ~5,000 tokens; description still ≤100 tokens.

- [ ] **Step 6: Commit**

```bash
git add SKILL.md references/tools.md references/troubleshooting.md references/slurm-hpc.md
git commit -m "docs: interrupt-first workflow — interrupt tool, real timeout, busy semantics"
```

---

### Task 9: Full regression + smoke

**Files:** none (verification only)

- [ ] **Step 1: Full suite**

Run: `uv run --with pytest --with pytest-asyncio --with mcp --with pydantic --with numpy --with matplotlib --with pandas python -m pytest tests/ -q`
Expected: all pass. Count: 144 existing + 4 (Task 1) + 3 (Task 2) + 2 (Task 3) + 5 (Task 4) + 5 (Task 5) + 3 (Task 6) + 4 (Task 7) = 170.

- [ ] **Step 2: Smoke test the real server over stdio**

Run: `echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' | uv run --with mcp --with pydantic python scripts/repl_server.py`
Expected: a JSON initialize result, then the process idles until EOF. (Matches the existing `test_smoke.py` pattern.)

- [ ] **Step 3: Final commit if the suite surfaced fixes**

```bash
git add -A
git commit -m "fix: regression cleanup after kernel-worker hardening"
```
(Skip if nothing changed.)
