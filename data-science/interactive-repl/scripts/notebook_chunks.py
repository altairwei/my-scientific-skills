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
    g.add_argument("--chunk", help="print the selected chunk's code (label, index, or range-like selector)")
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
        print("\n".join(c.code for c in sel))
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
