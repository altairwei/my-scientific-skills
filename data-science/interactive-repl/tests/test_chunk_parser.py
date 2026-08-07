import json
import pytest
from pathlib import Path

import _chunk_parser

HERE = Path(__file__).resolve().parent
IPYNB = HERE / "fixtures" / "notebook.ipynb"
RMD = HERE / "fixtures" / "notebook.Rmd"
QMD = HERE / "fixtures" / "notebook.qmd"


# ---- Task 1: .ipynb ----
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


# ---- Task 2: .Rmd / .qmd ----
def test_parse_rmd_engine_label_and_index():
    chunks = _chunk_parser.parse_notebook(str(RMD))
    assert [c.index for c in chunks] == [1, 2, 3, 4, 5]
    assert [c.label for c in chunks] == ["setup", "load-data", "unnamed-3", "unnamed-4", "boom"]
    assert all(c.language == "r" for c in chunks)


def test_parse_rmd_header_include_false():
    chunks = _chunk_parser.parse_notebook(str(RMD))
    assert chunks[0].include is False    # {r setup, include=FALSE}
    assert chunks[1].include is True
    assert chunks[0].eval is True        # include=FALSE does not imply eval=FALSE


def test_parse_rmd_header_eval_false():
    chunks = _chunk_parser.parse_notebook(str(RMD))
    assert chunks[2].eval is False       # {r, eval=FALSE}


def test_parse_rmd_body_extracted_without_fence():
    chunks = _chunk_parser.parse_notebook(str(RMD))
    assert "x <- 1" in chunks[0].code
    assert "```" not in chunks[0].code    # fence lines stripped


def test_parse_qmd_pipe_options_label_include_eval():
    chunks = _chunk_parser.parse_notebook(str(QMD))
    assert [c.label for c in chunks] == ["setup-qmd", "py-chunk", "unnamed-3", "visible-r"]
    assert [c.language for c in chunks] == ["r", "python", "r", "r"]
    assert chunks[0].include is False    # #| include: false
    assert chunks[2].eval is False       # #| eval: false
    assert chunks[1].eval is True


def test_parse_qmd_pipe_option_lines_stripped_from_code():
    chunks = _chunk_parser.parse_notebook(str(QMD))
    assert "#|" not in chunks[0].code
    assert "#|" not in chunks[2].code


def test_parse_qmd_label_from_pipe_when_no_fence_label():
    # chunk 1 has no fence label but #| label: setup-qmd
    chunks = _chunk_parser.parse_notebook(str(QMD))
    assert chunks[0].label == "setup-qmd"
