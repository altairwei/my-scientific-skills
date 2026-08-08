import pytest


@pytest.mark.asyncio
async def test_base_sidecar_loaded_at_start(monkeypatch, tmp_path):
    """_peek/_who/_fig are auto-injected at session start — no explicit inject call."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        # _who() exists without an inject call → base sidecar auto-loaded
        r = await client.call_tool("run_code", {"session": "py:sc", "code": "_who()"})
        assert r.structured_content["error"] is None


@pytest.mark.asyncio
async def test_peek_summarizes_dataframe(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code",
            {"session": "py:pk", "code": "import pandas as pd; df = pd.DataFrame({'a':[1,2],'b':['x','y']})"})
        r = await client.call_tool("run_code", {"session": "py:pk", "code": "print(_peek(df))"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "DataFrame" in sc["stdout"]
