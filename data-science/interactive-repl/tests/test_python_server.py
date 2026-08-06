import pytest


@pytest.mark.asyncio
async def test_run_code_auto_starts_session(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "t1", "code": "1 + 1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]


@pytest.mark.asyncio
async def test_persistence_across_calls(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "t2", "code": "x = 10"})
        r = await client.call_tool("run_code", {"session": "t2", "code": "x * 5"})
        assert "50" in r.structured_content["stdout"]


@pytest.mark.asyncio
async def test_named_sessions_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "a", "code": "y = 1"})
        await client.call_tool("run_code", {"session": "b", "code": "y = 2"})
        ra = await client.call_tool("run_code", {"session": "a", "code": "y"})
        rb = await client.call_tool("run_code", {"session": "b", "code": "y"})
        assert "1" in ra.structured_content["stdout"]
        assert "2" in rb.structured_content["stdout"]


@pytest.mark.asyncio
async def test_restart_clears_state(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "t3", "code": "z = 99"})
        await client.call_tool("restart", {"session": "t3"})
        r = await client.call_tool("run_code", {"session": "t3", "code": "z"})
        assert r.structured_content["error"] is not None  # NameError after restart
