# Notebook Chunk Parsing + Selective Execution — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a parse-and-select layer to the `interactive-repl` skill so the agent can list code chunks in `.Rmd`/`.qmd`/`.ipynb` notebooks and selectively run one or a range in the persistent REPL — in dependency order, respecting chunk options, routing each chunk to the matching language server.

**Architecture:** A shared pure-stdlib parser (`_chunk_parser.py`) handles all three formats. A read-only CLI (`notebook_chunks.py`) lists/extracts chunks (no session). A new `run_chunk(session, file, selector)` MCP tool on **both** `python-repl` and `r-repl` servers parses → resolves the selector → runs each chunk via the existing `_call_worker`, skipping `eval=FALSE` and wrong-language chunks (reported in `skipped`), stopping on first error. Read-only on the notebook file; outputs to disk + `Read` like `run_code`.

**Tech Stack:** Python 3.10+ stdlib only for the parser/CLI (no R, no pydantic, no external deps); `mcp` SDK v2 + `pydantic` for the `run_chunk` tool (already deps of both servers). Test stack: `pytest`, `pytest-asyncio` (already configured via `pyproject.toml` `asyncio_mode = "auto"`).

**Spec:** `docs/superpowers/specs/2026-08-07-notebook-chunks-design.md` — read it for the *why* behind every choice. This plan is the *how*.

**Existing patterns this plan reuses (verified in the codebase):**
- `import _common` works in both servers because each does `sys.path.insert(0, str(HERE))` (see `python_repl_server.py:14-17`). `import _chunk_parser` follows the same pattern.
- `_call_worker(session, code) -> dict` returns `{stdout, stderr, error, plots, truncated, degraded}` on success, and `error="worker died: ..."` on broken pipe (see `python_repl_server.py:112-127`). `run_chunk` loops it per chunk.
- `_get(session)` auto-creates the session on first use (`python_repl_server.py:104-109`).
- `@mcp.tool()` + Pydantic `BaseModel` return → `structured_content` is the model as dict (verified in `test_python_server.py`). Nested models work (`VarList` → `list[VarSummary]`).
- Test style: `from mcp import Client`; `async with Client(mcp) as client: r = await client.call_tool(name, args)`; read `r.structured_content` (the model as dict).

---

## File Structure

```
data-science/interactive-repl/
├── scripts/
│   ├── _chunk_parser.py          # NEW — pure-stdlib parser: file → [Chunk] + resolve_selector
│   ├── notebook_chunks.py        # NEW — read-only CLI: list / extract chunks
│   ├── python_repl_server.py     # MODIFIED — + RunChunkResult model + run_chunk tool
│   └── r_repl_server.py          # MODIFIED — + RunChunkResult model + run_chunk tool
├── references/
│   └── notebook-iteration.md     # NEW — workflow guidance
├── tests/
│   ├── fixtures/
│   │   ├── notebook.ipynb        # NEW — 4 Python cells (incl. skip-execution + erroring)
│   │   ├── notebook.Rmd          # NEW — 5 R chunks (include=FALSE, eval=FALSE, boom)
│   │   └── notebook.qmd          # NEW — 4 mixed chunks (#| label, #| include, #| eval)
│   ├── test_chunk_parser.py      # NEW
│   ├── test_notebook_cli.py      # NEW
│   ├── test_python_server.py     # MODIFIED — +4 run_chunk tests
│   └── test_r_server.py          # MODIFIED — +4 run_chunk tests
└── SKILL.md                      # MODIFIED — notebook section, tools list, deep-docs, replace hand-wave
```

Each file has one responsibility. `_chunk_parser.py` is pure stdlib (no I/O beyond `Path.read_text`) so it is unit-testable in isolation and the CLI runs anywhere. The two `run_chunk` tools are mirrored across the two servers (same as `run_code`), differing only in `_LANG`.

**Phases (natural shippable boundaries):**
- **Phase 1 — Parser** (Tasks 1–3): `_chunk_parser.py` + fixtures + tests.
- **Phase 2 — CLI** (Task 4): `notebook_chunks.py` + tests.
- **Phase 3 — `run_chunk` tool** (Tasks 5–6): both servers + tests.
- **Phase 4 — Ship** (Tasks 7–8): guidance reference + `SKILL.md`.

Run tests from the skill root: `cd data-science/interactive-repl && python -m pytest tests/ -v` (or `uv run pytest`). The `conftest.py` already puts `scripts/` on `sys.path` so `import _chunk_parser` works in tests.

---

## Phase 1 — Parser

### Task 1: `_chunk_parser.py` skeleton + `.ipynb` parsing

**Files:**
- Create: `data-science/interactive-repl/scripts/_chunk_parser.py`
- Create: `data-science/interactive-repl/tests/fixtures/notebook.ipynb`
- Test: `data-science/interactive-repl/tests/test_chunk_parser.py`

- [ ] **Step 1: Create the `.ipynb` fixture**

Create `tests/fixtures/notebook.ipynb` with exactly this content (4 code cells; cell 2 has a `skip-execution` tag → `eval=False`; cell 4 raises):

```json
{
 "cells": [
  {"cell_type": "markdown", "metadata": {}, "source": ["# Test notebook\n"]},
  {"cell_type": "code", "execution_count": 1, "metadata": {}, "outputs": [], "source": ["x = 1\n", "print(x)\n"]},
  {"cell_type": "code", "execution_count": 2, "metadata": {"tags": ["skip-execution"]}, "outputs": [], "source": ["print(\"skipped cell\")\n"]},
  {"cell_type": "code", "execution_count": 3, "metadata": {}, "outputs": [], "source": ["y = x + 1\n", "print(y)\n"]},
  {"cell_type": "code", "execution_count": 4, "metadata": {}, "outputs": [], "source": ["raise RuntimeError(\"boom\")\n"]}
 ],
 "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}, "language_info": {"name": "python"}},
 "nbformat": 4,
 "nbformat_minor": 5
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_chunk_parser.py`:

```python
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
```

Create the `notebook.txt` placeholder referenced by the unknown-ext test (any content):

```bash
echo "not a notebook" > data-science/interactive-repl/tests/fixtures/notebook.txt
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd data-science/interactive-repl && python -m pytest tests/test_chunk_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named '_chunk_parser'`.

- [ ] **Step 4: Write `_chunk_parser.py` (ipynb path only — `.rmd`/`.qmd` come in Task 2)**

Create `scripts/_chunk_parser.py`:

```python
"""Notebook chunk parser (pure stdlib). Parses .ipynb (and .Rmd/.qmd in Task 2) into
ordered code chunks with metadata. No R, no pydantic, no external deps — runs anywhere
with python3/uv. Used by notebook_chunks.py (CLI) and both repl servers (run_chunk tool).

.ipynb: json cells where cell_type=='code'; language from metadata.kernelspec.language.
        A 'skip-execution' cell tag sets eval=False.
.Rmd/.qmd: line-based fence parser (added in Task 2).
"""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass
class Chunk:
    index: int = 0          # 1-based, notebook-global (set by parse_notebook)
    label: str = ""         # knitr label, or "unnamed-<index>"
    language: str = ""      # 'r' | 'python' | <engine>, lowercased
    code: str = ""          # chunk body, #| option lines stripped
    eval: bool = True
    include: bool = True
    source: str = ""        # absolute path of the notebook


def parse_notebook(path: str) -> list[Chunk]:
    """Parse a .ipynb/.Rmd/.qmd notebook into an ordered list of code chunks.

    Raises FileNotFoundError if the file is missing, ValueError for an unsupported
    extension or a notebook with no code chunks.
    """
    p = Path(path).resolve()
    if not p.exists():
        raise FileNotFoundError(f"file not found: {path}")
    suffix = p.suffix.lower()
    if suffix == ".ipynb":
        chunks = _parse_ipynb(p)
    else:
        raise ValueError(
            f"unsupported file type: {suffix or '(none)'} (expected .Rmd/.qmd/.ipynb)")
    for i, c in enumerate(chunks, 1):
        c.index = i
        if not c.label:
            c.label = f"unnamed-{i}"
    if not chunks:
        raise ValueError(f"no code chunks found in {p.name}")
    return chunks


def _parse_ipynb(p: Path) -> list[Chunk]:
    data = json.loads(p.read_text())
    lang = (data.get("metadata", {}).get("kernelspec", {}) or {}) \
        .get("language", "python").lower()
    chunks: list[Chunk] = []
    for cell in data.get("cells", []):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", [])
        code = "".join(src) if isinstance(src, list) else str(src)
        tags = cell.get("metadata", {}).get("tags", []) or []
        ev = "skip-execution" not in tags
        chunks.append(Chunk(label="", language=lang, code=code.rstrip("\n"),
                            eval=ev, source=str(p)))
    return chunks
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd data-science/interactive-repl && python -m pytest tests/test_chunk_parser.py -v`
Expected: PASS (7 tests).

- [ ] **Step 6: Commit**

```bash
cd data-science/interactive-repl
git add scripts/_chunk_parser.py tests/fixtures/notebook.ipynb tests/fixtures/notebook.txt tests/test_chunk_parser.py
git commit -m "Add _chunk_parser: Chunk dataclass + .ipynb parsing (skip-execution tag)"
```

---

### Task 2: `.Rmd`/`.qmd` fence parser + chunk options

**Files:**
- Modify: `data-science/interactive-repl/scripts/_chunk_parser.py` (add `.rmd`/`.qmd` branch + `_parse_rmd`)
- Create: `data-science/interactive-repl/tests/fixtures/notebook.Rmd`
- Create: `data-science/interactive-repl/tests/fixtures/notebook.qmd`
- Test: `data-science/interactive-repl/tests/test_chunk_parser.py` (append tests)

- [ ] **Step 1: Create the `.Rmd` fixture**

Create `tests/fixtures/notebook.Rmd` (5 R chunks: `include=FALSE`, named, `eval=FALSE`, unnamed, erroring):

```
---
title: "Test Rmd"
---

```{r setup, include=FALSE}
x <- 1
```

Some narrative.

```{r load-data}
df <- data.frame(a = 1:3)
```

```{r, eval=FALSE}
print("do not run me")
```

```{r}
print(x)
```

```{r boom}
stop("boom")
```
```

- [ ] **Step 2: Create the `.qmd` fixture**

Create `tests/fixtures/notebook.qmd` (4 chunks, mixed R/Python, `#|` Quarto options):

```
---
title: "Test qmd"
---

```{r}
#| label: setup-qmd
#| include: false
x <- 1
```

```{python}
#| label: py-chunk
print("hello from python")
```

```{r}
#| eval: false
print("r chunk eval false")
```

```{r visible-r}
print(x)
```
```

- [ ] **Step 3: Write the failing tests (append to `tests/test_chunk_parser.py`)**

```python
RMD = HERE / "fixtures" / "notebook.Rmd"
QMD = HERE / "fixtures" / "notebook.qmd"


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
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd data-science/interactive-repl && python -m pytest tests/test_chunk_parser.py -v`
Expected: FAIL — `.rmd`/`.qmd` raise `ValueError("unsupported file type")` (the `else` branch).

- [ ] **Step 5: Implement — add the `.rmd`/`.qmd` branch to `parse_notebook`**

In `scripts/_chunk_parser.py`, edit `parse_notebook` to add the branch (replace the `if/else` block):

```python
    if suffix == ".ipynb":
        chunks = _parse_ipynb(p)
    elif suffix in (".rmd", ".qmd"):
        chunks = _parse_rmd(p)
    else:
        raise ValueError(
            f"unsupported file type: {suffix or '(none)'} (expected .Rmd/.qmd/.ipynb)")
```

- [ ] **Step 6: Implement — add `_parse_rmd` and its helpers**

Append to `scripts/_chunk_parser.py` (add `import re` to the top imports first):

```python
import re

_OPEN_RE = re.compile(r"^```\{(\w+)\s*([^}]*)")
_CLOSE_RE = re.compile(r"^```\s*$")


def _parse_rmd(p: Path) -> list[Chunk]:
    lines = p.read_text().splitlines()
    chunks: list[Chunk] = []
    i, n = 0, len(lines)
    while i < n:
        m = _OPEN_RE.match(lines[i])
        if not m:
            i += 1
            continue
        engine = m.group(1).lower()
        fence_label, opts = _split_header(m.group(2))
        body, j = [], i + 1
        while j < n and not _CLOSE_RE.match(lines[j]):
            body.append(lines[j])
            j += 1
        i = j + 1  # j is the closing fence (or EOF)
        # merge #| cell-option lines into opts; keep the rest as code
        cell_opts = dict(opts)
        code_lines = []
        for bl in body:
            mm = re.match(r"^#\|\s*(.+)$", bl)
            if mm:
                _merge_opt(cell_opts, mm.group(1))
            else:
                code_lines.append(bl)
        code = "\n".join(code_lines).strip("\n")
        label = fence_label or cell_opts.get("label", "")
        ev = _opt_bool(cell_opts.get("eval"), True)
        inc = _opt_bool(cell_opts.get("include"), True)
        purl = _opt_bool(cell_opts.get("purl"), True)
        if not purl:
            continue  # purl=FALSE → excluded entirely (knitr semantics)
        chunks.append(Chunk(label=label, language=engine, code=code,
                            eval=ev, include=inc, source=str(p)))
    return chunks


def _split_header(header: str) -> tuple[str, dict[str, str]]:
    """Split 'label, eval=FALSE, include=FALSE' into (label, {eval:'FALSE', ...})."""
    opts: dict[str, str] = {}
    label = ""
    for part in [s.strip() for s in header.split(",") if s.strip()]:
        if "=" in part:
            k, _, v = part.partition("=")
            opts[k.strip().lower()] = v.strip()
        elif not label:
            label = part
    return label, opts


def _merge_opt(opts: dict[str, str], raw: str) -> None:
    """Parse a #| line body ('eval: false' or 'eval=FALSE') into opts (in place)."""
    raw = raw.strip()
    if ":" in raw and "=" not in raw:
        raw = raw.replace(":", "=", 1)
    if "=" in raw:
        k, _, v = raw.partition("=")
        opts[k.strip().lower()] = v.strip()


def _opt_bool(val: str | None, default: bool) -> bool:
    if val is None:
        return default
    return val.strip().lower() not in ("false", "f", "0", "no")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd data-science/interactive-repl && python -m pytest tests/test_chunk_parser.py -v`
Expected: PASS (14 tests: 7 from Task 1 + 7 new).

- [ ] **Step 8: Commit**

```bash
cd data-science/interactive-repl
git add scripts/_chunk_parser.py tests/fixtures/notebook.Rmd tests/fixtures/notebook.qmd tests/test_chunk_parser.py
git commit -m "Add _chunk_parser: .Rmd/.qmd fence parser + chunk options (eval/include/purl)"
```

---

### Task 3: `resolve_selector` (label / index / range)

**Files:**
- Modify: `data-science/interactive-repl/scripts/_chunk_parser.py` (add `resolve_selector`)
- Test: `data-science/interactive-repl/tests/test_chunk_parser.py` (append tests)

- [ ] **Step 1: Write the failing tests (append to `tests/test_chunk_parser.py`)**

```python
def _chunks():
    return _chunk_parser.parse_notebook(str(IPYNB))


def test_resolve_selector_single_index():
    sel = _chunk_parser.resolve_selector(_chunks(), "2")
    assert len(sel) == 1 and sel[0].index == 2


def test_resolve_selector_label():
    rmd = _chunk_parser.parse_notebook(str(RMD))
    sel = _chunk_parser.resolve_selector(rmd, "boom")
    assert len(sel) == 1 and sel[0].label == "boom"


def test_resolve_selector_range():
    sel = _chunk_parser.resolve_selector(_chunks(), "2-4")
    assert [c.index for c in sel] == [2, 3, 4]


def test_resolve_selector_open_range():
    sel = _chunk_parser.resolve_selector(_chunks(), "3-")
    assert [c.index for c in sel] == [3, 4]


def test_resolve_selector_numeric_takes_precedence_over_label():
    # A purely-numeric selector resolves as an index, not a label.
    sel = _chunk_parser.resolve_selector(_chunks(), "1")
    assert sel[0].index == 1


def test_resolve_selector_out_of_bounds_raises():
    with pytest.raises(ValueError, match="out of bounds"):
        _chunk_parser.resolve_selector(_chunks(), "0")
    with pytest.raises(ValueError, match="out of bounds"):
        _chunk_parser.resolve_selector(_chunks(), "99")


def test_resolve_selector_not_found_raises():
    with pytest.raises(ValueError, match="not found"):
        _chunk_parser.resolve_selector(_chunks(), "nope")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd data-science/interactive-repl && python -m pytest tests/test_chunk_parser.py -v -k resolve`
Expected: FAIL with `AttributeError: module '_chunk_parser' has no attribute 'resolve_selector'`.

- [ ] **Step 3: Implement `resolve_selector`**

Append to `scripts/_chunk_parser.py`:

```python
def resolve_selector(chunks: list[Chunk], selector: str) -> list[Chunk]:
    """Resolve a selector to an ordered list of chunks.

    Order of resolution: range (`N-M` or `N-`) → index (`N`) → label. Numeric
    selectors take precedence over label — a chunk labelled purely with digits is
    pathological. Raises ValueError on out-of-bounds or no match (with available
    labels in the message).
    """
    if re.fullmatch(r"\d+-\d*", selector):
        a, _, b = selector.partition("-")
        start = int(a)
        end = int(b) if b else len(chunks)
        if start < 1 or end > len(chunks) or start > end:
            raise ValueError(f"range '{selector}' out of bounds (1-{len(chunks)})")
        return chunks[start - 1:end]
    if re.fullmatch(r"\d+", selector):
        idx = int(selector)
        if idx < 1 or idx > len(chunks):
            raise ValueError(f"index {idx} out of bounds (1-{len(chunks)})")
        return [chunks[idx - 1]]
    matches = [c for c in chunks if c.label == selector]
    if not matches:
        labels = ", ".join(c.label for c in chunks)
        raise ValueError(
            f"chunk '{selector}' not found. Available: {labels} (indices 1-{len(chunks)})")
    return matches
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd data-science/interactive-repl && python -m pytest tests/test_chunk_parser.py -v`
Expected: PASS (21 tests total).

- [ ] **Step 5: Commit**

```bash
cd data-science/interactive-repl
git add scripts/_chunk_parser.py tests/test_chunk_parser.py
git commit -m "Add _chunk_parser.resolve_selector (label/index/range, numeric precedence)"
```

---

## Phase 2 — CLI

### Task 4: `notebook_chunks.py` (list / extract, read-only)

**Files:**
- Create: `data-science/interactive-repl/scripts/notebook_chunks.py`
- Test: `data-science/interactive-repl/tests/test_notebook_cli.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_notebook_cli.py`:

```python
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
    assert 'stop("intentional error")' in r.stdout


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd data-science/interactive-repl && python -m pytest tests/test_notebook_cli.py -v`
Expected: FAIL — `notebook_chunks.py` does not exist (subprocess exits 2 / file not found).

- [ ] **Step 3: Implement `notebook_chunks.py`**

Create `scripts/notebook_chunks.py`:

```python
#!/usr/bin/env python3
# data-science/interactive-repl/scripts/notebook_chunks.py
"""List or extract code chunks from .Rmd/.qmd/.ipynb notebooks.

Read-only, no session. Default prints a human table; --json prints full descriptors;
--chunk SEL / --chunks RNG print chunk code to stdout (pipe to run_code or inspect).
Extraction does NOT respect eval=FALSE — that is a run_chunk semantic, not an
extraction semantic.

Run: uv run scripts/notebook_chunks.py FILE [--json | --chunk SEL | --chunks RNG]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _chunk_parser  # noqa: E402


def _chunk_to_dict(c: _chunk_parser.Chunk) -> dict:
    return {"index": c.index, "label": c.label, "language": c.language,
            "code": c.code, "eval": c.eval, "include": c.include}


def _table(chunks: list[_chunk_parser.Chunk]) -> str:
    lines = [f"{'#':>3}  {'label':<20} {'lang':<8} {'eval':<5} {'lines':>5}"]
    for c in chunks:
        ev = "yes" if c.eval else "no"
        nlines = len(c.code.splitlines()) if c.code else 0
        lines.append(f"{c.index:>3}  {c.label:<20} {c.language:<8} {ev:<5} {nlines:>5}")
    lines.append(f"\n{len(chunks)} chunk(s)")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="List/extract notebook code chunks.")
    ap.add_argument("file")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--json", action="store_true", help="full chunk descriptors as JSON")
    g.add_argument("--chunk", help="print one chunk's code (label or 1-based index)")
    g.add_argument("--chunks", help="print concatenated code for a range (N-M or N-)")
    args = ap.parse_args()

    try:
        chunks = _chunk_parser.parse_notebook(args.file)
    except (FileNotFoundError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([_chunk_to_dict(c) for c in chunks],
                         indent=2, ensure_ascii=False))
    elif args.chunk:
        try:
            sel = _chunk_parser.resolve_selector(chunks, args.chunk)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(sel[0].code)
    elif args.chunks:
        try:
            sel = _chunk_parser.resolve_selector(chunks, args.chunks)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print("\n".join(c.code for c in sel))
    else:
        print(_table(chunks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd data-science/interactive-repl && python -m pytest tests/test_notebook_cli.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
cd data-science/interactive-repl
git add scripts/notebook_chunks.py tests/test_notebook_cli.py
git commit -m "Add notebook_chunks.py CLI (list/extract chunks, read-only, no session)"
```

---

## Phase 3 — `run_chunk` MCP tool

### Task 5: `run_chunk` on `python-repl` server

**Files:**
- Modify: `data-science/interactive-repl/scripts/python_repl_server.py` (add `import _chunk_parser`, `RunChunkResult` model, `run_chunk` tool)
- Test: `data-science/interactive-repl/tests/test_python_server.py` (append 4 tests)

- [ ] **Step 1: Write the failing tests (append to `tests/test_python_server.py`)**

```python
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
```

Add `import pathlib` to the test file's imports if not present (the existing file starts with `import pytest`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd data-science/interactive-repl && python -m pytest tests/test_python_server.py -v -k run_chunk`
Expected: FAIL — `run_chunk` tool not found (the server has no such tool).

- [ ] **Step 3: Implement — add the import**

In `scripts/python_repl_server.py`, the existing block (lines 14–17) is:

```python
HERE = Path(__file__).resolve().parent
WORKER = HERE / "python_worker.py"
sys.path.insert(0, str(HERE))
import _common  # noqa: E402
```

Change the last line to import `_chunk_parser` too:

```python
HERE = Path(__file__).resolve().parent
WORKER = HERE / "python_worker.py"
sys.path.insert(0, str(HERE))
import _common  # noqa: E402
import _chunk_parser  # noqa: E402
```

- [ ] **Step 4: Implement — add the `RunChunkResult` model + `_LANG`**

After the existing `RunResult` class (after line 29) and before `SessionInfo`, insert:

```python
class ChunkRan(BaseModel):
    index: int
    label: str
    language: str


class ChunkSkipped(BaseModel):
    index: int
    label: str
    language: str
    reason: str


class RunChunkResult(BaseModel):
    stdout: str
    stderr: str
    error: str | None = None
    plots: list[str] = Field(default_factory=list)
    truncated: bool = False
    degraded: bool = False
    ran: list[ChunkRan] = Field(default_factory=list)
    skipped: list[ChunkSkipped] = Field(default_factory=list)
    failed_chunk: ChunkRan | None = None


_LANG = "python"
```

- [ ] **Step 5: Implement — add the `run_chunk` tool**

After the existing `run_code` tool (after its `return _to_run_result(...)` line, before `session_info`), insert:

```python
@mcp.tool()
def run_chunk(session: str, file: str, selector: str) -> RunChunkResult:
    """Run one chunk (or a range) from a .Rmd/.qmd/.ipynb notebook in the session.
    selector = label | index | 'N-M' | 'N-'. Parses, resolves, runs each chunk in
    notebook order via the session worker. Skips eval=FALSE and wrong-language chunks
    (listed in `skipped`). Stops on first error (dependency order). Pass an absolute
    `file` path — the server's cwd may differ from the agent's."""
    try:
        chunks = _chunk_parser.parse_notebook(file)
    except (FileNotFoundError, ValueError) as e:
        return RunChunkResult(stdout="", stderr="", error=str(e))
    try:
        selected = _chunk_parser.resolve_selector(chunks, selector)
    except ValueError as e:
        return RunChunkResult(stdout="", stderr="", error=str(e))

    ran: list[ChunkRan] = []
    skipped: list[ChunkSkipped] = []
    out_parts: list[str] = []
    err_parts: list[str] = []
    plots: list[str] = []
    truncated = False
    degraded = False
    for c in selected:
        if not c.eval:
            skipped.append(ChunkSkipped(index=c.index, label=c.label,
                                        language=c.language, reason="eval=FALSE"))
            continue
        if c.language != _LANG:
            other = "r-repl" if _LANG == "python" else "python-repl"
            skipped.append(ChunkSkipped(index=c.index, label=c.label, language=c.language,
                                        reason=f"language={c.language}, use {other}"))
            continue
        r = _call_worker(session, c.code)
        if r.get("error"):
            return RunChunkResult(
                stdout="\n".join(s for s in out_parts if s),
                stderr="\n".join(s for s in err_parts if s),
                error=r["error"], plots=plots, truncated=truncated, degraded=degraded,
                ran=ran, skipped=skipped,
                failed_chunk=ChunkRan(index=c.index, label=c.label, language=c.language))
        out_parts.append(r.get("stdout", ""))
        err_parts.append(r.get("stderr", ""))
        plots.extend(r.get("plots") or [])
        truncated = truncated or r.get("truncated", False)
        degraded = degraded or r.get("degraded", False)
        ran.append(ChunkRan(index=c.index, label=c.label, language=c.language))
    return RunChunkResult(
        stdout="\n".join(s for s in out_parts if s),
        stderr="\n".join(s for s in err_parts if s),
        error=None, plots=plots, truncated=truncated, degraded=degraded,
        ran=ran, skipped=skipped, failed_chunk=None)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd data-science/interactive-repl && python -m pytest tests/test_python_server.py -v`
Expected: PASS (all existing tests + 4 new run_chunk tests).

- [ ] **Step 7: Commit**

```bash
cd data-science/interactive-repl
git add scripts/python_repl_server.py tests/test_python_server.py
git commit -m "Add run_chunk tool to python-repl (parse/select/run, eval+lang skip, stop-on-error)"
```

---

### Task 6: `run_chunk` on `r-repl` server (mirror)

**Files:**
- Modify: `data-science/interactive-repl/scripts/r_repl_server.py` (add `import _chunk_parser`, `RunChunkResult` model, `run_chunk` tool with `_LANG = "r"`)
- Test: `data-science/interactive-repl/tests/test_r_server.py` (append 4 tests)

- [ ] **Step 1: Write the failing tests (append to `tests/test_r_server.py`)**

```python
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
        # range 4-5: chunk 4 (print(x)) runs; chunk 5 (stop("boom")) errors → stop
        r = await client.call_tool("run_chunk", {"session": "rrc4", "file": str(rmd), "selector": "4-5"})
        sc = r.structured_content
        assert sc["error"] is not None
        assert "boom" in sc["error"]
        assert sc["failed_chunk"]["index"] == 5
        assert [c["index"] for c in sc["ran"]] == [4]
```

Add `import pathlib` to the test file's imports if not present (the existing file starts with `import pytest`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd data-science/interactive-repl && python -m pytest tests/test_r_server.py -v -k run_chunk`
Expected: FAIL — `run_chunk` tool not found on `r-repl`.

- [ ] **Step 3: Implement — add the import**

In `scripts/r_repl_server.py`, the existing block (lines 16–19) is:

```python
HERE = Path(__file__).resolve().parent
REPL_R = HERE / "repl.R"
sys.path.insert(0, str(HERE))
import _common  # noqa: E402
```

Change the last line to:

```python
HERE = Path(__file__).resolve().parent
REPL_R = HERE / "repl.R"
sys.path.insert(0, str(HERE))
import _common  # noqa: E402
import _chunk_parser  # noqa: E402
```

- [ ] **Step 4: Implement — add the `RunChunkResult` model + `_LANG`**

After the existing `RunResult` class (after line 39) and before `VarSummary`, insert the same model block as Task 5 (Step 4), but with `_LANG = "r"`:

```python
class ChunkRan(BaseModel):
    index: int
    label: str
    language: str


class ChunkSkipped(BaseModel):
    index: int
    label: str
    language: str
    reason: str


class RunChunkResult(BaseModel):
    stdout: str
    stderr: str
    error: str | None = None
    plots: list[str] = Field(default_factory=list)
    truncated: bool = False
    degraded: bool = False
    ran: list[ChunkRan] = Field(default_factory=list)
    skipped: list[ChunkSkipped] = Field(default_factory=list)
    failed_chunk: ChunkRan | None = None


_LANG = "r"
```

- [ ] **Step 5: Implement — add the `run_chunk` tool**

After the existing `run_code` tool (after its `return _to_run_result(...)` line, before `list_variables`), insert the **same** `run_chunk` body as Task 5 Step 5 (the `other` branch resolves to `python-repl` when `_LANG == "r"`). The full function:

```python
@mcp.tool()
def run_chunk(session: str, file: str, selector: str) -> RunChunkResult:
    """Run one chunk (or a range) from a .Rmd/.qmd/.ipynb notebook in the session.
    selector = label | index | 'N-M' | 'N-'. Parses, resolves, runs each chunk in
    notebook order via the session worker. Skips eval=FALSE and wrong-language chunks
    (listed in `skipped`). Stops on first error (dependency order). Pass an absolute
    `file` path — the server's cwd may differ from the agent's."""
    try:
        chunks = _chunk_parser.parse_notebook(file)
    except (FileNotFoundError, ValueError) as e:
        return RunChunkResult(stdout="", stderr="", error=str(e))
    try:
        selected = _chunk_parser.resolve_selector(chunks, selector)
    except ValueError as e:
        return RunChunkResult(stdout="", stderr="", error=str(e))

    ran: list[ChunkRan] = []
    skipped: list[ChunkSkipped] = []
    out_parts: list[str] = []
    err_parts: list[str] = []
    plots: list[str] = []
    truncated = False
    degraded = False
    for c in selected:
        if not c.eval:
            skipped.append(ChunkSkipped(index=c.index, label=c.label,
                                        language=c.language, reason="eval=FALSE"))
            continue
        if c.language != _LANG:
            other = "r-repl" if _LANG == "python" else "python-repl"
            skipped.append(ChunkSkipped(index=c.index, label=c.label, language=c.language,
                                        reason=f"language={c.language}, use {other}"))
            continue
        r = _call_worker(session, c.code)
        if r.get("error"):
            return RunChunkResult(
                stdout="\n".join(s for s in out_parts if s),
                stderr="\n".join(s for s in err_parts if s),
                error=r["error"], plots=plots, truncated=truncated, degraded=degraded,
                ran=ran, skipped=skipped,
                failed_chunk=ChunkRan(index=c.index, label=c.label, language=c.language))
        out_parts.append(r.get("stdout", ""))
        err_parts.append(r.get("stderr", ""))
        plots.extend(r.get("plots") or [])
        truncated = truncated or r.get("truncated", False)
        degraded = degraded or r.get("degraded", False)
        ran.append(ChunkRan(index=c.index, label=c.label, language=c.language))
    return RunChunkResult(
        stdout="\n".join(s for s in out_parts if s),
        stderr="\n".join(s for s in err_parts if s),
        error=None, plots=plots, truncated=truncated, degraded=degraded,
        ran=ran, skipped=skipped, failed_chunk=None)
```

- [ ] **Step 6: Run the full suite to verify it passes**

Run: `cd data-science/interactive-repl && python -m pytest tests/ -v`
Expected: PASS (all prior tests + 4 new r-repl run_chunk tests). This also re-runs the Python `run_chunk` tests and the parser/CLI tests — confirms no regression.

- [ ] **Step 7: Commit**

```bash
cd data-science/interactive-repl
git add scripts/r_repl_server.py tests/test_r_server.py
git commit -m "Add run_chunk tool to r-repl (mirror of python-repl, _LANG=r)"
```

---

## Phase 4 — Ship

### Task 7: `references/notebook-iteration.md`

**Files:**
- Create: `data-science/interactive-repl/references/notebook-iteration.md`

- [ ] **Step 1: Write the reference doc**

Create `references/notebook-iteration.md`:

````markdown
# Notebook iteration — `.Rmd` / `.qmd` / `.ipynb`

The REPL is for iterating on chunks of a notebook the way you would in RStudio / VSCode /
Jupyter: list the chunks, run one or a range in dependency order, see the output, fix the
chunk, re-run. State persists in the session — do not restart between chunks.

## List chunks (no session)

`notebook_chunks.py FILE` prints a table (index, label, language, eval, line count).
`--json` gives full descriptors (with code) for inspection before running. `--chunk SEL`
or `--chunks N-M` print the code to stdout. This is read-only — it never runs anything.

```bash
uv run scripts/notebook_chunks.py analysis.qmd            # table
uv run scripts/notebook_chunks.py analysis.qmd --json     # full descriptors
uv run scripts/notebook_chunks.py analysis.qmd --chunk extract   # one chunk's code
```

## Run chunks (one call)

`run_chunk(session, file, selector)` on the matching server parses, resolves, and runs each
chunk in notebook order. `selector` = label (`extract`), index (`3`), range (`3-7`), or
open range (`3-` = to end). Returns `{stdout, stderr, error, plots, ran, skipped,
failed_chunk}`.

- `ran` — chunks that executed (index/label/language).
- `skipped` — chunks not run, with a reason: `eval=FALSE` or `language=<lang>, use <other>-repl`.
- `failed_chunk` — the chunk that errored, if `error` is set. Later chunks are not run.

## Cross-language routing

A `.qmd` or `.ipynb` can mix R and Python chunks. `run_chunk` on **r-repl** runs only
`language == "r"` chunks; on **python-repl** only `language == "python"`. The rest appear
in `skipped` with a routing hint. For a mixed notebook, call `run_chunk` on each server:
R chunks on `r-repl`, Python chunks on `python-repl`.

## Pass absolute file paths

`run_chunk` runs in the server process, whose cwd may differ from yours. Pass an absolute
`file` path — the same convention as `source()`/`read.csv()`/`read.csv()` in `SKILL.md`.

## Chunk options

- `eval=FALSE` / `#| eval: false` → the chunk is listed but `run_chunk` skips it (reason
  `eval=FALSE`). To force-run it, extract the code with the CLI and pass it to `run_code`.
- `include=FALSE` → the chunk still runs; the flag is informational. (Deviation from knitr:
  the REPL is transparent — we surface output rather than hide it.)
- `purl=FALSE` → the chunk is excluded from the list entirely (knitr semantics).

## The iterate loop

1. `notebook_chunks.py FILE` → see chunks (labels, languages, eval flags).
2. `run_chunk(session, FILE, selector)` → run one or a range; check `ran` / `skipped` /
   `error`.
3. If a chunk errors, **`Edit` the notebook file** to fix it, then `run_chunk` again —
   state persists, do not restart.
4. Plots auto-save to disk + `Read` (same as `run_code`).

## Not for headless render

To execute a whole notebook and write outputs back into it, use `quarto render` or
`jupyter nbconvert --execute`. This skill is REPL iteration: read-only on the file, outputs
to disk. `run_chunk` and the CLI never write to the notebook.

## Limitation + escape hatch

The `.Rmd`/`.qmd` parser is a pure-Python fence parser (no R dependency) so both servers
and the CLI parse all three formats. It is best-effort: a literal triple-backtick *inside*
a chunk body (rare) can confuse it. For 100% knitr fidelity, tangle the file on `r-repl`:

```r
knitr::purl("analysis.qmd", output = "/tmp/analysis.R", documentation = 1)
```

then read `/tmp/analysis.R` and pass chunks to `run_code`.
````

- [ ] **Step 2: Commit**

```bash
cd data-science/interactive-repl
git add references/notebook-iteration.md
git commit -m "Add notebook-iteration reference (list/run workflow, routing, options, escape hatch)"
```

---

### Task 8: `SKILL.md` — notebook section, tools list, deep-docs, replace hand-wave

**Files:**
- Modify: `data-science/interactive-repl/SKILL.md`

- [ ] **Step 1: Add `run_chunk` to the tools list**

In `SKILL.md`, the tools list currently contains a `run_code` bullet and others. After the
`run_code` bullet (the line starting `- \`run_code(session, code)\``), insert:

```markdown
- `run_chunk(session, file, selector)` — run one chunk (or a range) from a `.Rmd`/`.qmd`/`.ipynb` notebook in the session. `selector` = label / index / `N-M` / `N-`. Routes by language; skips `eval=FALSE`. See `references/notebook-iteration.md`.
```

- [ ] **Step 2: Add the notebook section + replace the hand-wave**

The current `## Ad-hoc inspection is first-class` section reads:

```markdown
## Ad-hoc inspection is first-class

`run_code` runs any code; use it freely for quick peeks (`_peek(df)`, `dim(df)`,
`head(df)`). For notebook/qmd workflows, extract a chunk's code (read the chunk body or
`knitr::purl`) and pass it to `run_code`.
```

Replace it with:

```markdown
## Ad-hoc inspection is first-class

`run_code` runs any code; use it freely for quick peeks (`_peek(df)`, `dim(df)`,
`head(df)`).

## Notebooks (.Rmd / .qmd / .ipynb)

For notebook workflows, don't hand-extract chunks — use the chunk tools. List chunks with
`notebook_chunks.py FILE` (no session), then `run_chunk(session, FILE, selector)` to run one
or a range in dependency order. Routes each chunk to the matching server by language (R →
`r-repl`, Python → `python-repl`); `eval=FALSE` chunks are skipped. Read-only on the file —
outputs to disk + `Read`. See `references/notebook-iteration.md` for the full workflow.
```

- [ ] **Step 3: Add the reference to "Deep docs"**

The current `## Deep docs` section ends with:

```markdown
Read on demand: `references/tools.md` (full API), `references/sidecar-authoring.md`
(how to write a sidecar for your skill), `references/r-setup.md` (conda env,
neutralized functions), `references/troubleshooting.md` (stuck code, missing deps,
worker crashes), `references/plot-iteration.md` (save-and-look, expanded).
```

Replace it with:

```markdown
Read on demand: `references/tools.md` (full API), `references/sidecar-authoring.md`
(how to write a sidecar for your skill), `references/r-setup.md` (conda env,
neutralized functions), `references/troubleshooting.md` (stuck code, missing deps,
worker crashes), `references/plot-iteration.md` (save-and-look, expanded),
`references/notebook-iteration.md` (`.Rmd`/`.qmd`/`.ipynb` chunk list + run).
```

- [ ] **Step 4: Verify the description still triggers correctly**

Run: `./count-skill-tokens.py data-science/interactive-repl`
Expected: SKILL.md under 500 lines / 5,000 tokens; description under 100 tokens (the
description is unchanged at 93 tokens, so this should still pass — confirm no growth
beyond limits from the new section).

- [ ] **Step 5: Run the full test suite once more**

Run: `cd data-science/interactive-repl && python -m pytest tests/ -v`
Expected: PASS (all tests; the SKILL.md edits don't affect tests, but this is the final
green-light gate before declaring done).

- [ ] **Step 6: Commit**

```bash
cd data-science/interactive-repl
git add SKILL.md
git commit -m "SKILL.md: add notebook section + run_chunk tool, replace hand-wave, deep-docs"
```

---

## Self-Review (run after writing the plan)

**1. Spec coverage** — every spec section maps to a task:
- §6 parser (`.ipynb` + `.Rmd`/`.qmd` fence + options + unnamed + language) → Tasks 1–2.
- §6 `resolve_selector` + selector grammar → Task 3.
- §7 CLI (table / `--json` / `--chunk` / `--chunks`) → Task 4.
- §8 `run_chunk` + `RunChunkResult` + behavior (parse → resolve → partition → run → stop-on-error) → Tasks 5–6.
- §9 selectors / semantics (label / index / `N-M` / `N-`; eval skip; purl exclusion; lang routing; read-only) → Tasks 3, 5, 6, 7.
- §10 error handling (file-not-found, unknown-ext, no-chunks, selector-not-found, stop-on-error, worker-died) → Tasks 1, 3, 4, 5, 6.
- §11 guidance (`references/notebook-iteration.md` + `SKILL.md` notebook section + tools list + deep-docs + replace hand-wave) → Tasks 7–8.
- §12 testing (parser, CLI, both servers) → Tasks 1–6.
- §13 scope v1/deferred — no task needed (deferred items are explicitly not built).

**2. Placeholder scan** — no "TBD"/"TODO"/"implement later"/"add appropriate …". Every code
step contains complete, runnable code. The "same body as Task 5 Step 5" in Task 6 Step 5 is
the one cross-reference — it is justified by repeating the **full** function body inline
there, so the engineer need not flip back.

**3. Type consistency** — `Chunk` fields (`index`, `label`, `language`, `code`, `eval`,
`include`, `source`) are identical in Task 1's dataclass and every test. `RunChunkResult`
fields (`ran`, `skipped`, `failed_chunk`) and `ChunkRan`/`ChunkSkipped` field names
(`index`, `label`, `language`, `reason`) match between Task 5 (python) and Task 6 (r), and
match the test assertions (`sc["ran"]`, `sc["skipped"]`, `sc["failed_chunk"]`,
`reason="eval=FALSE"`, `reason~"language=..."`). `resolve_selector` is defined in Task 3
and used in Tasks 4, 5, 6 with the same signature. `_LANG` is `"python"` in Task 5 and
`"r"` in Task 6 (the only intentional difference).

No issues found. Plan is complete.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-07-notebook-chunks.md`. Two execution options:

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
