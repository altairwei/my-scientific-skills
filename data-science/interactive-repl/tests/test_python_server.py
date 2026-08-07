import pathlib
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


@pytest.mark.asyncio
async def test_list_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "lv", "code": "a = 1; b = [1,2,3]"})
        r = await client.call_tool("list_variables", {"session": "lv"})
        names = [v["name"] for v in r.structured_content["variables"]]
        assert "a" in names and "b" in names


@pytest.mark.asyncio
async def test_inject_sidecar(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    sidecar = tmp_path / "k.py"
    sidecar.write_text("def hello():\n    return 'injected'\n")
    async with Client(mcp) as client:
        await client.call_tool("inject", {"session": "inj", "path": str(sidecar)})
        r = await client.call_tool("run_code", {"session": "inj", "code": "hello()"})
        assert "injected" in r.structured_content["stdout"]


@pytest.mark.asyncio
async def test_run_chunk_by_index(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    ipynb = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.ipynb"
    async with Client(mcp) as client:
        r = await client.call_tool("run_chunk", {"session": "rc1", "file": str(ipynb), "selector": "1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert any(c["index"] == 1 for c in sc["ran"])
        assert "1" in sc["stdout"]            # print(x) where x=1


@pytest.mark.asyncio
async def test_run_chunk_range_skips_eval_false(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    ipynb = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.ipynb"
    async with Client(mcp) as client:
        r = await client.call_tool("run_chunk", {"session": "rc2", "file": str(ipynb), "selector": "1-3"})
        sc = r.structured_content
        assert sc["error"] is None
        assert [c["index"] for c in sc["ran"]] == [1, 3]      # cell 2 eval=False skipped
        assert [c["index"] for c in sc["skipped"]] == [2]
        assert sc["skipped"][0]["reason"] == "eval=FALSE"
        assert "1" in sc["stdout"] and "2" in sc["stdout"]    # print(x)=1, print(y)=2 (x from cell 1)


@pytest.mark.asyncio
async def test_run_chunk_wrong_language_skipped(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    qmd = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.qmd"
    async with Client(mcp) as client:
        # selector "1-4" on python-repl: only chunk 2 (py-chunk) is python; 1,3,4 are r
        r = await client.call_tool("run_chunk", {"session": "rc3", "file": str(qmd), "selector": "1-4"})
        sc = r.structured_content
        assert sc["error"] is None
        assert [c["index"] for c in sc["ran"]] == [2]
        assert sorted(c["index"] for c in sc["skipped"]) == [1, 3, 4]
        skip_by = {s["index"]: s["reason"] for s in sc["skipped"]}
        assert "language=r" in skip_by[1]        # chunk 1: r, eval=True → language skip
        assert skip_by[3] == "eval=FALSE"        # chunk 3: r AND eval=false → eval wins
        assert "language=r" in skip_by[4]        # chunk 4: r, eval=True → language skip
        assert "hello from python" in sc["stdout"]


@pytest.mark.asyncio
async def test_run_chunk_stop_on_first_error(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from python_repl_server import mcp
    ipynb = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.ipynb"
    async with Client(mcp) as client:
        # range 1-4: cells 1 (runs), 2 (eval=F skip), 3 (runs, x set by cell 1), 4 (raise boom → stop)
        r = await client.call_tool("run_chunk", {"session": "rc4", "file": str(ipynb), "selector": "1-4"})
        sc = r.structured_content
        assert sc["error"] is not None
        assert "boom" in sc["error"]
        assert sc["failed_chunk"]["index"] == 4
        assert [c["index"] for c in sc["ran"]] == [1, 3]       # 4 not run; 2 skipped
        assert [c["index"] for c in sc["skipped"]] == [2]
