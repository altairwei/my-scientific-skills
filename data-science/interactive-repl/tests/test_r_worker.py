import json, os, socket, subprocess, pathlib

HERE = pathlib.Path(__file__).parent
REPL_R = HERE.parent / "scripts" / "repl.R"


def _spawn_and_connect():
    """Test listens on a TCP localhost ephemeral port; R connects as a client."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0)); srv.listen(1); srv.settimeout(20)
    port = srv.getsockname()[1]
    proc = subprocess.Popen(
        ["R", "--no-save", "--no-restore", "-f", str(REPL_R)],
        env={**os.environ, "REPL_PORT": str(port)},
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    conn, _ = srv.accept()
    # read the ready marker
    buf = b""
    while not buf.endswith(b"\n"):
        buf += conn.recv(65536)
    ready = json.loads(buf.decode())
    assert ready.get("ready") is True, f"bad ready marker: {ready}"
    return proc, conn


def _call(conn, code, rid="t"):
    conn.sendall((json.dumps({"id": rid, "code": code}) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = conn.recv(65536)
        if not chunk:
            break
        buf += chunk
    return json.loads(buf.decode())


def test_r_roundtrip(tmp_path):
    proc, conn = _spawn_and_connect()
    try:
        r = _call(conn, "1 + 1")
        assert r["error"] is None
        assert "2" in r["stdout"]
    finally:
        proc.terminate(); conn.close()


def test_r_persistence(tmp_path):
    proc, conn = _spawn_and_connect()
    try:
        _call(conn, "x <- 42")
        r = _call(conn, "x * 2")
        assert "84" in r["stdout"]
    finally:
        proc.terminate(); conn.close()


def test_r_error_returns_response(tmp_path):
    proc, conn = _spawn_and_connect()
    try:
        r = _call(conn, "stop('boom')")
        assert r["error"] is not None and "boom" in r["error"]
        # session still usable after an error
        r2 = _call(conn, "1 + 1")
        assert r2["error"] is None and "2" in r2["stdout"]
    finally:
        proc.terminate(); conn.close()


def test_r_ggplot_saved_to_png(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    proc, conn = _spawn_and_connect()
    try:
        # last expression is the ggplot (visible) → withVisible → ggsave
        r = _call(conn, "library(ggplot2); "
                        "ggplot(data.frame(x=1:3, y=c(1,4,9)), aes(x,y)) + geom_point() + geom_line()")
        assert r["error"] is None
        assert len(r["plots"]) >= 1
        import os
        assert os.path.exists(r["plots"][0])
    finally:
        proc.terminate(); conn.close()


def test_dt_table_overridden_to_kable(tmp_path):
    proc, conn = _spawn_and_connect()
    try:
        r = _call(conn, "dt_table(data.frame(a=1:3, b=c('x','y','z')))")
        assert r["error"] is None
        assert "|" in r["stdout"]  # kable prints a markdown-style table
    finally:
        proc.terminate(); conn.close()
