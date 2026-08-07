import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLI = HERE.parent / "scripts" / "notebook_chunks.py"
IPYNB = HERE / "fixtures" / "notebook.ipynb"
RMD = HERE / "fixtures" / "notebook.Rmd"


def _run(*args):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True)


def test_cli_default_table_lists_chunks():
    r = _run(str(IPYNB))
    assert r.returncode == 0
    assert "unnamed-1" in r.stdout
    assert "python" in r.stdout
    assert "no" in r.stdout       # cell 2 eval=False → "no" in the eval column


def test_cli_json_outputs_full_descriptors():
    r = _run(str(IPYNB), "--json")
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert len(data) == 4
    assert data[0]["language"] == "python"
    assert data[1]["eval"] is False
    assert "code" in data[0]


def test_cli_chunk_by_index_prints_code():
    r = _run(str(IPYNB), "--chunk", "1")
    assert r.returncode == 0
    assert "x = 1" in r.stdout
    assert "print(x)" in r.stdout


def test_cli_chunk_by_label_prints_code():
    r = _run(str(RMD), "--chunk", "boom")
    assert r.returncode == 0
    assert 'stop("boom")' in r.stdout


def test_cli_chunks_range_concatenates():
    r = _run(str(IPYNB), "--chunks", "1-3")
    assert r.returncode == 0
    assert "x = 1" in r.stdout              # cell 1
    assert "skipped cell" in r.stdout      # cell 2 (extraction ignores eval=FALSE)
    assert "y = x + 1" in r.stdout          # cell 3


def test_cli_bad_selector_exits_nonzero():
    r = _run(str(IPYNB), "--chunk", "nope")
    assert r.returncode == 1
    assert "not found" in r.stderr


def test_cli_missing_file_exits_nonzero():
    r = _run("/nonexistent.ipynb")
    assert r.returncode == 1
    assert "error" in r.stderr.lower()
