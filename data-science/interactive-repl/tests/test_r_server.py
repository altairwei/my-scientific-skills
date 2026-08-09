import pathlib
import pytest


@pytest.mark.asyncio
async def test_r_run_code(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "r:r1", "code": "1 + 1"})
        assert r.structured_content["error"] is None
        assert "2" in r.structured_content["stdout"]


@pytest.mark.asyncio
async def test_r_persistence_and_list_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "r:r2", "code": "df <- data.frame(a=1:3)"})
        r = await client.call_tool("list_variables", {"session": "r:r2"})
        names = [v["name"] for v in r.structured_content["variables"]]
        assert "df" in names


@pytest.mark.asyncio
async def test_r_inject_sidecar(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    sidecar = tmp_path / "k.R"
    sidecar.write_text("hello_r <- function() 'injected'\n")
    async with Client(mcp) as client:
        await client.call_tool("inject", {"session": "r:r3", "path": str(sidecar)})
        r = await client.call_tool("run_code", {"session": "r:r3", "code": "hello_r()"})
        assert "injected" in r.structured_content["stdout"]


@pytest.mark.asyncio
async def test_r_run_chunk_by_label(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    rmd = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.Rmd"
    async with Client(mcp) as client:
        r = await client.call_tool("run_chunk", {"session": "r:rrc1", "file": str(rmd), "selector": "setup"})
        sc = r.structured_content
        assert sc["error"] is None
        assert any(c["index"] == 1 for c in sc["ran"])


@pytest.mark.asyncio
async def test_r_run_chunk_range_skips_eval_false(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    rmd = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.Rmd"
    async with Client(mcp) as client:
        # range 1-4: chunks 1,2,4 run; chunk 3 eval=FALSE skipped; chunk 5 (boom) not in range
        r = await client.call_tool("run_chunk", {"session": "r:rrc2", "file": str(rmd), "selector": "1-4"})
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
    from repl_server import mcp
    qmd = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.qmd"
    async with Client(mcp) as client:
        # selector "2" on an r: session: chunk 2 is python (py-chunk) → skipped
        r = await client.call_tool("run_chunk", {"session": "r:rrc3", "file": str(qmd), "selector": "2"})
        sc = r.structured_content
        assert sc["error"] is None
        assert sc["ran"] == []
        assert sc["skipped"][0]["index"] == 2
        assert "language=python" in sc["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_r_run_chunk_stop_on_first_error(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    rmd = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.Rmd"
    async with Client(mcp) as client:
        # range 1-5: 1 (x<-1), 2 (df), 3 (eval=F skip), 4 (print(x)→"1"), 5 (stop("boom") → error → stop)
        r = await client.call_tool("run_chunk", {"session": "r:rrc4", "file": str(rmd), "selector": "1-5"})
        sc = r.structured_content
        assert sc["error"] is not None
        assert "boom" in sc["error"]
        assert sc["failed_chunk"]["index"] == 5
        assert [c["index"] for c in sc["ran"]] == [1, 2, 4]   # 3 skipped, 5 errored (not in ran)
        assert [c["index"] for c in sc["skipped"]] == [3]


@pytest.mark.asyncio
async def test_r_user_con_does_not_clobber_protocol(monkeypatch, tmp_path):
    """P0 #1: user `con <- ...` must NOT kill the worker — protocol socket is in .repl."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "r:con1", "code": 'con <- "userdata"; print(con)'})
        assert r.structured_content["error"] is None
        assert "userdata" in r.structured_content["stdout"]
        # a subsequent call must still work — proves the protocol socket survived
        r2 = await client.call_tool("run_code", {"session": "r:con1", "code": "1 + 1"})
        assert r2.structured_content["error"] is None
        assert "2" in r2.structured_content["stdout"]


@pytest.mark.asyncio
async def test_r_single_plot_returns_array(monkeypatch, tmp_path):
    """P0 #2: a single ggplot must serialize plots as a 1-element array, not a scalar."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "r:plot1", "code": "ggplot2::qplot(1:3, 4:6)"})
        sc = r.structured_content
        assert sc["error"] is None
        assert isinstance(sc["plots"], list)
        assert len(sc["plots"]) == 1


@pytest.mark.asyncio
async def test_r_list_variables_excludes_protocol_state(monkeypatch, tmp_path):
    """#4: protocol vars live in .repl/local(); ls(.GlobalEnv) lists user objects only."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "r:lv2", "code": "x <- 1; y <- 2"})
        r = await client.call_tool("list_variables", {"session": "r:lv2"})
        names = [v["name"] for v in r.structured_content["variables"]]
        assert "x" in names and "y" in names
        for leaked in ("con", "port", "run_cell", "write_json", "req", "res", "rid", "line", "dt_table"):
            assert leaked not in names, f"{leaked} leaked in list_variables"


@pytest.mark.asyncio
async def test_r_dt_table_fallback_after_rm(monkeypatch, tmp_path):
    """#5: rm('dt_table') removes the user's; the worker's attached fallback still resolves."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "r:dt1", "code": 'dt_table <- function() "user version"'})
        r = await client.call_tool("run_code", {"session": "r:dt1", "code": "rm(dt_table); print(exists('dt_table', inherits=TRUE))"})
        assert r.structured_content["error"] is None
        assert "TRUE" in r.structured_content["stdout"]   # attached fallback found via search path


@pytest.mark.asyncio
async def test_r_run_chunk_sets_cwd_to_notebook_dir(monkeypatch, tmp_path):
    """#3: run_chunk sets the session cwd to the notebook's dir so relative paths resolve."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    nb = tmp_path / "cwd.Rmd"
    nb.write_text('```{r}\nprint(getwd())\n```\n')
    async with Client(mcp) as client:
        r = await client.call_tool("run_chunk", {"session": "r:cwd1", "file": str(nb), "selector": "1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert str(tmp_path) in sc["stdout"]


@pytest.mark.asyncio
async def test_r_run_chunk_run_above(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    rmd = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.Rmd"
    async with Client(mcp) as client:
        # ^load-data → chunks 1..2 (setup + load-data)
        r = await client.call_tool("run_chunk", {"session": "r:rra1", "file": str(rmd), "selector": "^load-data"})
        sc = r.structured_content
        assert sc["error"] is None
        assert [c["index"] for c in sc["ran"]] == [1, 2]
        assert sc["skipped"] == []


@pytest.mark.asyncio
async def test_r_child_output_tolerated(monkeypatch, tmp_path):
    """R system() output leaks raw lines onto the protocol stream — the
    tolerant reader skips non-JSON lines and returns the matching response."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "r:noise1", "code": 'system("echo RAW-NOISE"); 1 + 1'})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]


@pytest.mark.asyncio
async def test_r_run_chunk_run_from(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    rmd = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.Rmd"
    async with Client(mcp) as client:
        # load-data^ → chunks 2..5; chunk 3 eval=FALSE skipped; chunk 4 (print(x)) errors
        # because x (set in chunk 1) isn't in the range → stop before chunk 5.
        r = await client.call_tool("run_chunk", {"session": "r:rrf1", "file": str(rmd), "selector": "load-data^"})
        sc = r.structured_content
        assert sc["error"] is not None
        assert "x" in sc["error"]                  # object 'x' not found (message is locale-dependent)
        assert sc["failed_chunk"]["index"] == 4
        assert [c["index"] for c in sc["ran"]] == [2]
        assert [c["index"] for c in sc["skipped"]] == [3]
