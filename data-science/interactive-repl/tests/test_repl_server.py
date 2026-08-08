import pytest


def test_import_smoke():
    from repl_server import mcp
    assert mcp is not None


def test_parse_session_known_prefixes():
    from repl_server import _parse_session, _LANGUAGES
    # every registry key is a valid prefix — driven by the registry so the
    # test stays correct as language entries are added
    for prefix in sorted(_LANGUAGES):
        assert _parse_session(f"{prefix}:lmp") == (prefix, "lmp")
        assert _parse_session(f"{prefix}:abc:def") == (prefix, "abc:def")  # bare may contain ':'
        assert _parse_session(f"{prefix}:") is None                       # empty bare name
        assert _parse_session(f"{prefix}:  lmp ") == (prefix, "lmp")      # whitespace trimmed
    assert _parse_session("lmp") is None          # no prefix
    assert _parse_session(":lmp") is None         # empty prefix
    assert _parse_session("x:lmp") is None        # unknown prefix
    assert _parse_session("python:lmp") is None   # 'python' is not 'py'
    assert _parse_session("py: ") is None         # whitespace-only bare


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
    sidecar = tmp_path / "kernel.py"
    sidecar.write_text("x = 1\n")
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_chunk", {"session": "lmp", "file": "x.Rmd", "selector": "1"})
        assert "ambiguous" in r.structured_content["error"]
        r = await client.call_tool("restart", {"session": "lmp"})
        assert r.structured_content["ok"] is False
        assert "ambiguous" in r.structured_content["message"]
        r = await client.call_tool("session_info", {"session": "lmp"})
        assert "ambiguous" in r.structured_content["error"]
        r = await client.call_tool("list_variables", {"session": "lmp"})
        assert "ambiguous" in r.structured_content["error"]
        r = await client.call_tool("inject", {"session": "lmp", "path": str(sidecar)})
        assert r.structured_content["ok"] is False
        r = await client.call_tool("inspect_variable", {"session": "lmp", "name": "x"})
        assert "ambiguous" in r.structured_content["error"]


@pytest.mark.asyncio
async def test_session_info_never_started(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("session_info", {"session": "py:never"})
        sc = r.structured_content
        assert sc["running"] is False
        assert sc["error"] is None


@pytest.mark.asyncio
async def test_session_name_whitespace_normalized(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:ws", "code": "x = 1"})
        r = await client.call_tool("session_info", {"session": "py:ws "})
        assert r.structured_content["running"] is True
