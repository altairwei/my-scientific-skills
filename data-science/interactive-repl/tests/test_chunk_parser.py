import json
import pytest
from pathlib import Path

import _chunk_parser

HERE = Path(__file__).resolve().parent
IPYNB = HERE / "fixtures" / "notebook.ipynb"


def test_parse_ipynb_returns_code_cells_only():
    chunks = _chunk_parser.parse_notebook(str(IPYNB))
    assert len(chunks) == 4  # markdown cell excluded
    assert all(c.language == "python" for c in chunks)


def test_parse_ipynb_skip_execution_tag_sets_eval_false():
    chunks = _chunk_parser.parse_notebook(str(IPYNB))
    assert chunks[1].eval is False           # cell 2 has skip-execution
    assert chunks[0].eval is True and chunks[2].eval is True and chunks[3].eval is True


def test_parse_ipynb_unnamed_labels_and_index():
    chunks = _chunk_parser.parse_notebook(str(IPYNB))
    assert [c.index for c in chunks] == [1, 2, 3, 4]
    assert [c.label for c in chunks] == ["unnamed-1", "unnamed-2", "unnamed-3", "unnamed-4"]


def test_parse_ipynb_code_joined():
    chunks = _chunk_parser.parse_notebook(str(IPYNB))
    assert "x = 1" in chunks[0].code
    assert "print(x)" in chunks[0].code


def test_parse_unknown_extension_raises():
    with pytest.raises(ValueError, match="unsupported file type"):
        _chunk_parser.parse_notebook(str(HERE / "fixtures" / "notebook.txt"))


def test_parse_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        _chunk_parser.parse_notebook("/nonexistent.ipynb")


def test_parse_no_chunks_raises(tmp_path):
    p = tmp_path / "empty.ipynb"
    p.write_text(json.dumps({"cells": [{"cell_type": "markdown", "source": ["only narrative"]}],
                            "metadata": {}, "nbformat": 4}))
    with pytest.raises(ValueError, match="no code chunks"):
        _chunk_parser.parse_notebook(str(p))
