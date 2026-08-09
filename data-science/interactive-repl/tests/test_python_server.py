import json
import pathlib
import sys

import pytest


@pytest.mark.asyncio
async def test_run_code_auto_starts_session(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "py:t1", "code": "1 + 1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert "2" in sc["stdout"]


@pytest.mark.asyncio
async def test_persistence_across_calls(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:t2", "code": "x = 10"})
        r = await client.call_tool("run_code", {"session": "py:t2", "code": "x * 5"})
        assert "50" in r.structured_content["stdout"]


@pytest.mark.asyncio
async def test_named_sessions_isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:a", "code": "y = 1"})
        await client.call_tool("run_code", {"session": "py:b", "code": "y = 2"})
        ra = await client.call_tool("run_code", {"session": "py:a", "code": "y"})
        rb = await client.call_tool("run_code", {"session": "py:b", "code": "y"})
        assert "1" in ra.structured_content["stdout"]
        assert "2" in rb.structured_content["stdout"]


@pytest.mark.asyncio
async def test_restart_clears_state(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:t3", "code": "z = 99"})
        await client.call_tool("restart", {"session": "py:t3"})
        r = await client.call_tool("run_code", {"session": "py:t3", "code": "z"})
        assert r.structured_content["error"] is not None  # NameError after restart


@pytest.mark.asyncio
async def test_list_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:lv", "code": "a = 1; b = [1,2,3]"})
        r = await client.call_tool("list_variables", {"session": "py:lv"})
        names = [v["name"] for v in r.structured_content["variables"]]
        assert "a" in names and "b" in names


@pytest.mark.asyncio
async def test_inject_sidecar(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    sidecar = tmp_path / "k.py"
    sidecar.write_text("def hello():\n    return 'injected'\n")
    async with Client(mcp) as client:
        await client.call_tool("inject", {"session": "py:inj", "path": str(sidecar)})
        r = await client.call_tool("run_code", {"session": "py:inj", "code": "hello()"})
        assert "injected" in r.structured_content["stdout"]


@pytest.mark.asyncio
async def test_run_chunk_by_index(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    ipynb = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.ipynb"
    async with Client(mcp) as client:
        r = await client.call_tool("run_chunk", {"session": "py:rc1", "file": str(ipynb), "selector": "1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert any(c["index"] == 1 for c in sc["ran"])
        assert "1" in sc["stdout"]            # print(x) where x=1


@pytest.mark.asyncio
async def test_run_chunk_range_skips_eval_false(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    ipynb = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.ipynb"
    async with Client(mcp) as client:
        r = await client.call_tool("run_chunk", {"session": "py:rc2", "file": str(ipynb), "selector": "1-3"})
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
    from repl_server import mcp
    qmd = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.qmd"
    async with Client(mcp) as client:
        # selector "1-4" on a py: session: only chunk 2 (py-chunk) is python; 1,3,4 are r
        r = await client.call_tool("run_chunk", {"session": "py:rc3", "file": str(qmd), "selector": "1-4"})
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
    from repl_server import mcp
    ipynb = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.ipynb"
    async with Client(mcp) as client:
        # range 1-4: cells 1 (runs), 2 (eval=F skip), 3 (runs, x set by cell 1), 4 (raise boom → stop)
        r = await client.call_tool("run_chunk", {"session": "py:rc4", "file": str(ipynb), "selector": "1-4"})
        sc = r.structured_content
        assert sc["error"] is not None
        assert "boom" in sc["error"]
        assert sc["failed_chunk"]["index"] == 4
        assert [c["index"] for c in sc["ran"]] == [1, 3]       # 4 not run; 2 skipped
        assert [c["index"] for c in sc["skipped"]] == [2]


@pytest.mark.asyncio
async def test_run_chunk_sets_cwd_to_notebook_dir(monkeypatch, tmp_path):
    """#3: run_chunk sets the session cwd to the notebook's dir so relative paths resolve."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    nb = tmp_path / "cwd.ipynb"
    nb.write_text(json.dumps({"cells": [{"cell_type": "code", "metadata": {}, "outputs": [], "source": ["import os; print(os.getcwd())\n"]}], "metadata": {"kernelspec": {"language": "python", "name": "python3"}}, "nbformat": 4, "nbformat_minor": 5}))
    async with Client(mcp) as client:
        r = await client.call_tool("run_chunk", {"session": "py:cwd1", "file": str(nb), "selector": "1"})
        sc = r.structured_content
        assert sc["error"] is None
        assert str(tmp_path) in sc["stdout"]


@pytest.mark.asyncio
async def test_list_variables_excludes_preimported_stdlib(monkeypatch, tmp_path):
    """#4 (Python): list_variables lists user objects, not the worker's pre-imported stdlib."""
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:lv3", "code": "x = 1"})
        r = await client.call_tool("list_variables", {"session": "py:lv3"})
        names = [v["name"] for v in r.structured_content["variables"]]
        assert "x" in names
        for leaked in ("json", "math", "os", "re", "sys"):
            assert leaked not in names, f"{leaked} leaked in list_variables"


@pytest.mark.asyncio
async def test_run_chunk_run_above(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    qmd = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.qmd"
    async with Client(mcp) as client:
        # ^py-chunk → chunks 1..2; chunk 1 is R → skipped (language), chunk 2 (python) runs
        r = await client.call_tool("run_chunk", {"session": "py:pra1", "file": str(qmd), "selector": "^py-chunk"})
        sc = r.structured_content
        assert sc["error"] is None
        assert [c["index"] for c in sc["ran"]] == [2]
        assert [c["index"] for c in sc["skipped"]] == [1]
        assert "hello from python" in sc["stdout"]


@pytest.mark.asyncio
async def test_run_chunk_run_from(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    qmd = pathlib.Path(__file__).resolve().parent / "fixtures" / "notebook.qmd"
    async with Client(mcp) as client:
        # py-chunk^ → chunks 2..4; 2 (python) runs, 3 (eval=FALSE) skipped, 4 (R) skipped
        r = await client.call_tool("run_chunk", {"session": "py:prf1", "file": str(qmd), "selector": "py-chunk^"})
        sc = r.structured_content
        assert sc["error"] is None
        assert [c["index"] for c in sc["ran"]] == [2]
        assert sorted(c["index"] for c in sc["skipped"]) == [3, 4]


@pytest.mark.asyncio
async def test_close_kills_and_evicts(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp, _sessions
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:cl1", "code": "x = 1"})
        assert "py:cl1" in _sessions
        ack = await client.call_tool("close", {"session": "py:cl1"})
        assert ack.structured_content["ok"] is True
        assert "closed session" in ack.structured_content["message"]
        assert "py:cl1" not in _sessions
        info = await client.call_tool("session_info", {"session": "py:cl1"})
        assert info.structured_content["running"] is False
        assert info.structured_content["pid"] is None


@pytest.mark.asyncio
async def test_close_then_run_code_is_fresh_namespace(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:cl2", "code": "z = 99"})
        await client.call_tool("close", {"session": "py:cl2"})
        r = await client.call_tool("run_code", {"session": "py:cl2", "code": "z"})
        assert r.structured_content["error"] is not None  # NameError after close


@pytest.mark.asyncio
async def test_close_idempotent_never_started(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        ack = await client.call_tool("close", {"session": "py:ghost"})
        assert ack.structured_content["ok"] is True
        assert "no running session" in ack.structured_content["message"]
        info = await client.call_tool("session_info", {"session": "py:ghost"})
        assert info.structured_content["running"] is False


@pytest.mark.asyncio
async def test_close_ambiguous_name_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        ack = await client.call_tool("close", {"session": "lmp"})
        assert ack.structured_content["ok"] is False
        assert "ambiguous session name" in ack.structured_content["message"]


@pytest.mark.asyncio
async def test_close_does_not_affect_other_sessions(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    from mcp import Client
    from repl_server import mcp
    async with Client(mcp) as client:
        await client.call_tool("run_code", {"session": "py:cl3", "code": "a = 1"})
        await client.call_tool("run_code", {"session": "py:cl4", "code": "b = 2"})
        ack = await client.call_tool("close", {"session": "py:cl3"})
        assert ack.structured_content["ok"] is True
        r = await client.call_tool("run_code", {"session": "py:cl4", "code": "b"})
        assert r.structured_content["error"] is None
        assert "2" in r.structured_content["stdout"]


@pytest.mark.asyncio
async def test_py_bin_env_selects_interpreter(monkeypatch, tmp_path):
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path))
    shim = tmp_path / "py-shim"
    shim.write_text("#!/bin/sh\nexec %s \"$@\"\n" % sys.executable)
    shim.chmod(0o755)
    monkeypatch.setenv("INTERACTIVE_REPL_PY_BIN", str(shim))
    from mcp import Client
    from repl_server import mcp, _sessions
    async with Client(mcp) as client:
        r = await client.call_tool("run_code", {"session": "py:pybin1", "code": "1 + 1"})
        assert r.structured_content["error"] is None
        assert "2" in r.structured_content["stdout"]
    assert _sessions["py:pybin1"].proc.args[0] == str(shim)  # env selected the interpreter
