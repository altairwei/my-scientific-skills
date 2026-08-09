import json, os, signal, subprocess, sys, pathlib, time
import pytest

import python_worker

HERE = pathlib.Path(__file__).parent
WORKER = HERE.parent / "scripts" / "python_worker.py"


def _spawn():
    p = subprocess.Popen(
        [sys.executable, str(WORKER)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    ready = json.loads(p.stdout.readline())
    assert ready.get("ready") is True, f"bad ready marker: {ready}"
    return p


def _call(p, code, rid="t"):
    p.stdin.write(json.dumps({"id": rid, "code": code}) + "\n")
    p.stdin.flush()
    return json.loads(p.stdout.readline())


def test_roundtrip_simple_expression():
    p = _spawn()
    try:
        r = _call(p, "1 + 1")
        assert r["id"] == "t"
        assert r["error"] is None
        assert "2" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_persistent_state_across_calls():
    p = _spawn()
    try:
        _call(p, "x = 42")
        r = _call(p, "x * 2")
        assert "84" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_error_still_returns_response():
    p = _spawn()
    try:
        r = _call(p, "raise ValueError('boom')")
        assert r["error"] is not None
        assert "boom" in r["error"]
        # session still usable after an error
        r2 = _call(p, "1 + 1")
        assert r2["error"] is None
        assert "2" in r2["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_multiline_exec():
    p = _spawn()
    try:
        # exec semantics: explicit print() — the last expression isn't auto-printed
        r = _call(p, "y = 0\nfor i in range(3): y += i\nprint(y)")
        assert r["error"] is None
        assert "3" in r["stdout"]  # 0 + 1 + 2
    finally:
        p.stdin.close(); p.terminate()


def test_matplotlib_figure_captured_to_png(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    p = _spawn()
    try:
        r = _call(p, "import matplotlib.pyplot as plt; plt.plot([1,2,3]); plt.xlabel('x')")
        assert r["error"] is None
        assert len(r["plots"]) >= 1
        assert os.path.exists(r["plots"][0])
        # figure was closed — a second call with no new figure returns no plots
        r2 = _call(p, "1 + 1")
        assert r2["plots"] == []
    finally:
        p.stdin.close(); p.terminate()


def test_plt_show_is_noop():
    p = _spawn()
    try:
        # plt.show() must not block — if it did, the call would hang and time out
        r = _call(p, "import matplotlib.pyplot as plt; plt.plot([1,2]); plt.show()")
        assert r["error"] is None
    finally:
        p.stdin.close(); p.terminate()


# ---- lazy dep install -------------------------------------------------------
# The server starts with only mcp+pydantic installed; numpy/pandas/matplotlib are
# fetched on first import via `uv pip install --target <py-site>` into a persistent
# dir. These unit-test the logic with subprocess.run mocked (no network).

def test_lazy_install_invokes_uv_pip_target(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    captured = {}
    def fake_run(cmd, **k):
        captured["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0)
    monkeypatch.setattr(python_worker.subprocess, "run", fake_run)
    assert python_worker._lazy_install("pandas") is True
    cmd = captured["cmd"]
    site_dir = f"py-site-{sys.version_info.major}.{sys.version_info.minor}"
    assert "pip" in cmd and "install" in cmd
    assert "--target" in cmd and "pandas" in cmd
    assert str(tmp_path / site_dir) in cmd
    assert str(tmp_path / site_dir) in sys.path   # added so the retry import finds it


def test_lazy_install_returns_false_on_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    def fake_run(cmd, **k):
        raise subprocess.CalledProcessError(1, cmd)
    monkeypatch.setattr(python_worker.subprocess, "run", fake_run)
    assert python_worker._lazy_install("pandas") is False


def test_import_wrapper_installs_on_missing(monkeypatch):
    calls = []
    def fake_orig(name, *a, **k):
        calls.append(name)
        if len(calls) == 1:
            raise ModuleNotFoundError("pandas")
        return "FAKE_PANDAS"
    installed = []
    monkeypatch.setattr(python_worker, "_lazy_install", lambda top: installed.append(top) or True)
    wrapper = python_worker._make_import_wrapper(fake_orig)
    mod = wrapper("pandas")
    assert mod == "FAKE_PANDAS"
    assert installed == ["pandas"]
    assert calls == ["pandas", "pandas"]   # initial miss + retry


def test_import_wrapper_reraises_unknown_module(monkeypatch):
    def fake_orig(name, *a, **k):
        raise ModuleNotFoundError("notapackage")
    installed = []
    monkeypatch.setattr(python_worker, "_lazy_install", lambda top: installed.append(top) or True)
    wrapper = python_worker._make_import_wrapper(fake_orig)
    with pytest.raises(ModuleNotFoundError):
        wrapper("notapackage")
    assert installed == []                 # not a lazy pkg → no install attempt


def test_import_wrapper_noop_when_present(monkeypatch):
    installed = []
    monkeypatch.setattr(python_worker, "_lazy_install", lambda top: installed.append(top) or True)
    def fake_orig(name, *a, **k):
        return "FAKE_MOD"
    wrapper = python_worker._make_import_wrapper(fake_orig)
    mod = wrapper("pandas")
    assert mod == "FAKE_MOD"
    assert installed == []                 # already present → no install


def test_capture_new_figures_does_not_import_matplotlib(monkeypatch):
    # If the user never imported matplotlib, _capture_new_figures must NOT trigger an
    # import (which would otherwise lazy-install matplotlib on every first cell).
    monkeypatch.delitem(sys.modules, "matplotlib", raising=False)
    monkeypatch.delitem(sys.modules, "matplotlib.pyplot", raising=False)
    assert python_worker._capture_new_figures() == []
    assert "matplotlib" not in sys.modules           # no import happened
    assert "matplotlib.pyplot" not in sys.modules


# ---- _CappedStringIO ---------------------------------------------------------

def test_capped_stringio_caps_at_byte_boundary():
    c = python_worker._CappedStringIO()
    c.write("x" * (python_worker._CappedStringIO.BUFFER_CAP + 1000))
    v = c.getvalue()
    assert len(v.encode("utf-8", "surrogatepass")) <= python_worker.MAX_OUTPUT
    assert "dropped" in v and "1000" in v
    assert c.truncated is True


def test_capped_stringio_utf8_boundary_trim():
    c = python_worker._CappedStringIO()
    big = "中" * (python_worker._CappedStringIO.BUFFER_CAP + 10)  # 3 bytes/char
    c.write(big)
    v = c.getvalue()
    v.encode("utf-8")  # must not raise — no split surrogate pair
    assert c.truncated is True


def test_capped_stringio_write_contract_and_no_cap():
    c = python_worker._CappedStringIO()
    assert c.write("hello") == 5          # io contract: code points written-or-consumed
    assert c.getvalue() == "hello"
    assert c.truncated is False
    # runaway loop style: repeated writes after the cap stay cheap, marker once
    c.write("x" * 2000000)
    assert c.truncated is True
    c.write("y" * 2000000)                # still cheap, no exception
    assert c.truncated is True


def test_runaway_print_capped_in_worker():
    p = _spawn()
    try:
        # tail-marker prints BEFORE the cap hits; the 5 MB write after it is capped
        r = _call(p, "print('x' * 800000); print('tail-marker'); print('y' * 5000000)")
        assert r["truncated"] is True
        assert "tail-marker" in r["stdout"]
        assert "dropped" in r["stdout"]
        assert len(r["stdout"]) < 2 * 1024 * 1024    # bounded even though 5 MB printed
    finally:
        p.stdin.close(); p.terminate()


# ---- hygiene: secrets / fd inheritance / linecache ---------------------------

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


# ---- exit()/quit() shadowing -------------------------------------------------

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


# ---- SIGINT discipline + interrupted/trace/usage -----------------------------

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


def test_worker_uses_preinstalled_py_site(monkeypatch, tmp_path):
    """A py-site-<ver> pre-populated by scripts/setup.sh is on sys.path from
    the start — imports work without the lazy-install hook re-fetching."""
    site = tmp_path / f"py-site-{sys.version_info.major}.{sys.version_info.minor}"
    site.mkdir()
    (site / "preinstalled_marker.py").write_text("VALUE = 'preinstalled'\n")
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    p = _spawn()
    try:
        r = _call(p, "import preinstalled_marker; print(preinstalled_marker.VALUE)")
        assert r["error"] is None
        assert "preinstalled" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()
