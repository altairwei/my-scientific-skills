import _common


def test_cap_output_truncates_with_marker():
    big = "x" * 1000
    out, truncated = _common.cap_output(big, max_bytes=100)
    assert len(out.encode()) <= 400  # head + marker, well under 1KB
    assert truncated is True
    assert "truncated" in out.lower()


def test_cap_output_short_unchanged():
    out, truncated = _common.cap_output("hi", max_bytes=100)
    assert out == "hi"
    assert truncated is False


def test_never_empty_returns_something_on_empty():
    out = _common.never_empty("", "an error happened")
    assert "an error" in out


def test_never_empty_keeps_stdout_when_present():
    out = _common.never_empty("real output", "some stderr")
    assert out == "real output"


def test_never_empty_when_both_empty():
    out = _common.never_empty("", "")
    assert out == "[no output]"


def test_plot_dir_is_under_data(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    d = _common.plot_dir()
    assert d.startswith(str(tmp_path))
    assert d.endswith("plots")


def test_json_line_roundtrip():
    msg = {"id": "x", "stdout": "hello\nworld", "error": None}
    line = _common.encode_line(msg)
    # JSON is a single line (newlines in values are escaped); one trailing \n terminator.
    assert line.count("\n") == 1
    assert line.endswith("\n")
    assert _common.decode_line(line) == msg
