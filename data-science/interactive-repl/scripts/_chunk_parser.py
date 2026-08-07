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
