import pathlib
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


@pytest.mark.asyncio
async def test_r_run_chunk_by_label(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from r_repl_server import mcp
    rmd = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.Rmd"
    async with Client(mcp) as client:
        r = await client.call_tool("run_chunk", {"session": "rrc1", "file": str(rmd), "selector": "setup"})
        sc = r.structured_content
        assert sc["error"] is None
        assert any(c["index"] == 1 for c in sc["ran"])


@pytest.mark.asyncio
async def test_r_run_chunk_range_skips_eval_false(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from r_repl_server import mcp
    rmd = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.Rmd"
    async with Client(mcp) as client:
        # range 1-4: chunks 1,2,4 run; chunk 3 eval=FALSE skipped; chunk 5 (boom) not in range
        r = await client.call_tool("run_chunk", {"session": "rrc2", "file": str(rmd), "selector": "1-4"})
        sc = r.structured_content
        assert sc["error"] is None
        assert [c["index"] for c in sc["ran"]] == [1, 2, 4]
        assert [c["index"] for c in sc["skipped"]] == [3]
        assert sc["skipped"][0]["reason"] == "eval=FALSE"
        assert "1" in sc["stdout"]            # print(x) where x <- 1 in chunk 1


@pytest.mark.asyncio
async def test_r_run_chunk_wrong_language_skipped(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from r_repl_server import mcp
    qmd = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.qmd"
    async with Client(mcp) as client:
        # selector "2" on r-repl: chunk 2 is python (py-chunk) → skipped
        r = await client.call_tool("run_chunk", {"session": "rrc3", "file": str(qmd), "selector": "2"})
        sc = r.structured_content
        assert sc["error"] is None
        assert sc["ran"] == []
        assert sc["skipped"][0]["index"] == 2
        assert "language=python" in sc["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_r_run_chunk_stop_on_first_error(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from r_repl_server import mcp
    rmd = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.Rmd"
    async with Client(mcp) as client:
        # range 1-5: 1 (x<-1), 2 (df), 3 (eval=F skip), 4 (print(x)→"1"), 5 (stop("boom") → error → stop)
        r = await client.call_tool("run_chunk", {"session": "rrc4", "file": str(rmd), "selector": "1-5"})
        sc = r.structured_content
        assert sc["error"] is not None
        assert "boom" in sc["error"]
        assert sc["failed_chunk"]["index"] == 5
        assert [c["index"] for c in sc["ran"]] == [1, 2, 4]   # 3 skipped, 5 errored (not in ran)
        assert [c["index"] for c in sc["skipped"]] == [3]
