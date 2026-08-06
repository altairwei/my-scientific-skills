import pytest


@pytest.mark.asyncio
async def test_r_base_sidecar_loaded_at_start(monkeypatch, tmp_path):
    """who/peek/fig are auto-sourced at R session start — no explicit inject."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from r_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "rsc", "code": "who()"})
        assert r.structured_content["error"] is None  # who() exists, no "could not find function"


@pytest.mark.asyncio
async def test_r_peek_summarizes_dataframe(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from r_repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "rpk", "code": "df <- data.frame(a=1:3, b=c('x','y','z'))"})
        r = await client.call_tool("run_code", {"session": "rpk", "code": "peek(df)"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "data.frame" in sc["stdout"]
