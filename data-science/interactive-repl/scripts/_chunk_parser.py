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
import re
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
    elif suffix in (".rmd", ".qmd"):
        chunks = _parse_rmd(p)
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
