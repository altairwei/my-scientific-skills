import json, subprocess, sys, pathlib

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
