import pytest


@pytest.mark.asyncio
async def test_r_run_code(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from r_repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "r1", "code": "1 + 1"})
        assert r.structured_content["error"] is None
        assert "2" in r.structured_content["stdout"]


@pytest.mark.asyncio
async def test_r_persistence_and_list_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from r_repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "r2", "code": "df <- data.frame(a=1:3)"})
        r = await client.call_tool("list_variables", {"session": "r2"})
        names = [v["name"] for v in r.structured_content["variables"]]
        assert "df" in names


@pytest.mark.asyncio
async def test_r_inject_sidecar(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from r_repl_server import mcp
    sidecar = tmp_path / "k.R"
    sidecar.write_text("hello_r <- function() 'injected'\n")
    async with Client(mcp) as client:
        await client.call_tool("inject", {"session": "r3", "path": str(sidecar)})
        r = await client.call_tool("run_code", {"session": "r3", "code": "hello_r()"})
        assert "injected" in r.structured_content["stdout"]
