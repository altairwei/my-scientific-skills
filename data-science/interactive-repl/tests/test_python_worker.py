import socket
import json, os, subprocess, sys, pathlib
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
    assert "pip" in cmd and "install" in cmd
    assert "--target" in cmd and "pandas" in cmd
    assert str(tmp_path / "py-site") in cmd
    assert str(tmp_path / "py-site") in sys.path   # added so the retry import finds it


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


def test_worker_tcp_mode_ready_and_roundtrip(monkeypatch, tmp_path):
    """Slurm mode: REPL_PORT set → worker speaks JSON-per-line over a TCP
    client socket; ready carries token + SLURM job info."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    monkeypatch.setenv("REPL_PORT", str(port))
    monkeypatch.setenv("REPL_HOST", "127.0.0.1")
    monkeypatch.setenv("REPL_TOKEN", "tok123")
    monkeypatch.setenv("SLURM_JOB_ID", "999")
    monkeypatch.setenv("SLURM_JOB_NODELIST", "cn001")
    proc = subprocess.Popen([sys.executable, str(WORKER)], env=os.environ,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True)
    try:
        conn, _ = srv.accept()
        buf = b""
        while not buf.endswith(b"\n"):
            buf += conn.recv(65536)
        ready = json.loads(buf.decode())
        assert ready["ready"] is True
        assert ready["token"] == "tok123"
        assert ready["job_id"] == "999"
        assert ready["node"] == "cn001"
        conn.sendall((json.dumps({"id": "r1", "code": "1 + 1"}) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            buf += conn.recv(65536)
        res = json.loads(buf.decode())
        assert res["id"] == "r1"
        assert res["error"] is None
        assert "2" in res["stdout"]
    finally:
        conn.close()
        proc.terminate()
        srv.close()
