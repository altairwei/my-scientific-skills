import json, os, subprocess, pathlib

HERE = pathlib.Path(__file__).parent
REPL_R = HERE.parent / "scripts" / "repl.R"


def _spawn():
    proc = subprocess.Popen(
        ["R", "--quiet", "--no-echo", "--no-save", "--no-restore", "-f", str(REPL_R)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, bufsize=1,
    )
    ready = json.loads(proc.stdout.readline())
    assert ready.get("ready") is True, f"bad ready marker: {ready}"
    return proc


def _call(p, code, rid="t"):
    p.stdin.write(json.dumps({"id": rid, "code": code}) + "\n")
    p.stdin.flush()
    line = p.stdout.readline()
    while line:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            line = p.stdout.readline()
            continue
        if obj.get("id") == rid:
            return obj
        line = p.stdout.readline()
    raise AssertionError("EOF before response")


def test_r_roundtrip():
    p = _spawn()
    try:
        r = _call(p, "1 + 1")
        assert r["error"] is None
        assert "2" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_r_persistence():
    p = _spawn()
    try:
        _call(p, "x <- 42")
        r = _call(p, "x * 2")
        assert "84" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_r_error_returns_response():
    p = _spawn()
    try:
        r = _call(p, "stop('boom')")
        assert r["error"] is not None and "boom" in r["error"]
        # session still usable after an error
        r2 = _call(p, "1 + 1")
        assert r2["error"] is None and "2" in r2["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_r_warning_captured_in_stderr_field():
    """Warnings are muffled (execution continues) and surface in stderr."""
    p = _spawn()
    try:
        r = _call(p, 'warning("careful"); 42')
        assert r["error"] is None
        assert "careful" in r["stderr"]
        assert "42" in r["stdout"]
    finally:
        p.stdin.close(); p.terminate()


def test_r_ggplot_saved_to_png(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    p = _spawn()
    try:
        # last expression is the ggplot (visible) → withVisible → ggsave
        r = _call(p, "library(ggplot2); "
                        "ggplot(data.frame(x=1:3, y=c(1,4,9)), aes(x,y)) + geom_point() + geom_line()")
        assert r["error"] is None
        assert len(r["plots"]) >= 1
        assert os.path.exists(r["plots"][0])
    finally:
        p.stdin.close(); p.terminate()


def test_dt_table_overridden_to_kable():
    p = _spawn()
    try:
        r = _call(p, "dt_table(data.frame(a=1:3, b=c('x','y','z')))")
        assert r["error"] is None
        assert "|" in r["stdout"]  # kable prints a markdown-style table
    finally:
        p.stdin.close(); p.terminate()
