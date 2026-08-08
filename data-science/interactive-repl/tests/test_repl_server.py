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
