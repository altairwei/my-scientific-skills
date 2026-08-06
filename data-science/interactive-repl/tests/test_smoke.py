"""Phase-1 smoke: launch python_repl_server.py over stdio (as the plugin would)
and call run_code via a real stdio client — validates the launch path, not just
the in-memory tool surface tested by test_python_server.py."""
import sys, pathlib, pytest
from mcp.client import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

HERE = pathlib.Path(__file__).resolve().parent
SERVER = HERE.parent / "scripts" / "python_repl_server.py"


@pytest.mark.asyncio
async def test_python_repl_stdio_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    params = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            r = await session.call_tool("run_code", {"session": "smoke", "code": "2 + 2"})
            sc = r.structured_content
            assert sc is not None
            assert sc["error"] is None
            assert "4" in sc["stdout"]
