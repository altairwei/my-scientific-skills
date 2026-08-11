#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = ["pypdfium2", "pillow", "pypdf"]
# ///
"""pdf_explore — stateless PDF navigation CLI for Claude Code.

Parses a PDF with pypdfium2 (text + page render) or pypdf (text-only
fallback), writing page text / figure renders to disk so the agent can
Read just what it needs without loading the whole PDF into context. No
LLM calls live here — semantic scan / per-page map / structured
extraction are Claude-orchestrated (in-context reasoning, or parallel
haiku Agent subagents over per-range text files). See SKILL.md.

Adapted from the pdf-explore skill's kernel.py (Apache-2.0). Dropped:
the host.llm fan-out (no equivalent in Claude Code — the Agent tool
with model:"haiku" replaces it, orchestrated by Claude, not a script),
the SAST prompt-injection guards (the script never interpolates page
text into an LLM prompt), and the PyMuPDF/fitz branch (AGPL-3.0 —
pypdfium2, Apache-2.0/BSD-3, already covers text + render).

Subcommands: info | outline | text | render | crop | grep
"""
import argparse
import hashlib
import json
import os
import re
import sys


PDF_AUTO_IMAGE_CHARS_THRESHOLD = 80
"""Mean chars/page below which a doc is probably a rasterized scan or an
image-only slide export — `text` warns to use `render` + Read instead,
since there's no text layer to extract."""


# ── page-range parsing ──────────────────────────────────────────────────────

def parse_pages(spec):
    """'5,21-25,62' → [5,21,22,23,24,25,62] (1-indexed, deduped, sorted).
    None / '' → None (all pages). Bad tokens are skipped with a warning."""
    if not spec:
        return None
    pages = set()
    for tok in spec.split(","):
        tok = tok.strip()
        if not tok:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", tok)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            if a > b:
                a, b = b, a
            pages.update(range(a, b + 1))
        elif re.fullmatch(r"\d+", tok):
            pages.add(int(tok))
        else:
            print(f"[pdf_explore] skipping bad page token {tok!r}", file=sys.stderr)
    return sorted(pages) if pages else None


# ── path resolution ─────────────────────────────────────────────────────────

def resolve_path(path):
    """Expand ~ and verify the file exists. No artifact-id resolution —
    Claude Code has no artifact store, unlike the original host platform."""
    if not isinstance(path, str) or not path:
        raise ValueError("pdf_explore: path must be a non-empty str")
    p = os.path.expanduser(path)
    if not os.path.exists(p):
        raise FileNotFoundError(f"pdf_explore: {path!r} not found")
    return p


# ── backends ────────────────────────────────────────────────────────────────

def _try_pdfium():
    """pypdfium2 if importable, else None. Lazy so --help works without deps."""
    try:
        import pypdfium2  # noqa: F401
        return pypdfium2
    except ImportError:
        return None


def _try_pypdf():
    try:
        from pypdf import PdfReader  # noqa: F401
        return PdfReader
    except ImportError:
        return None


def _pdfium_doc(path):
    """Open a pypdfium2 doc, raising a clear error on password-protected PDFs
    (pypdfium2 raises something opaque mentioning 'password')."""
    import pypdfium2 as pdfium
    try:
        return pdfium.PdfDocument(path)
    except Exception as e:
        if "password" in str(e).lower():
            raise ValueError(
                f"pdf_explore: {path!r} is password-protected. Decrypt it "
                f"first — e.g. `qpdf --decrypt --password=... in.pdf out.pdf`, "
                f"or `pypdfium2.PdfDocument(path, password=pw)`."
            ) from e
        raise


def page_count(path):
    """Number of pages, via whichever backend opens."""
    pdfium = _try_pdfium()
    if pdfium is not None:
        doc = _pdfium_doc(path)
        try:
            return len(doc)
        finally:
            doc.close()
    PdfReader = _try_pypdf()
    if PdfReader is not None:
        return len(PdfReader(path).pages)
    raise ImportError(
        "pdf_explore needs pypdfium2 or pypdf. They're in the inline "
        "# /// script deps — `uv run scripts/pdf_explore.py …` installs "
        "them automatically. If that failed, run scripts/setup.sh."
    )


def extract_text(path, pages=None):
    """Return [{page, text, n_chars}, ...] in page order (1-indexed).
    pypdfium2 gives the text layer; pypdf is a text-only fallback when
    pypdfium2 isn't installed. `pages` (1-indexed list or None=all)
    restricts the range — extracting a section costs only those pages."""
    path = resolve_path(path)
    want = pages  # 1-indexed list or None
    pdfium = _try_pdfium()
    if pdfium is not None:
        doc = _pdfium_doc(path)
        out = []
        try:
            total = len(doc)
            idxs = (range(total) if want is None
                    else sorted(i - 1 for i in want if 1 <= i <= total))
            for i in idxs:
                pg = doc[i]
                tp = pg.get_textpage()
                try:
                    # pdfium emits \r\n — normalize so char counts and grep
                    # match the text layer exactly.
                    txt = tp.get_text_bounded().replace("\r\n", "\n")
                finally:
                    tp.close()
                out.append({"page": i + 1, "text": txt, "n_chars": len(txt)})
        finally:
            doc.close()
        return out

    PdfReader = _try_pypdf()
    if PdfReader is not None:
        reader = PdfReader(path)
        total = len(reader.pages)
        idxs = (range(total) if want is None
                else sorted(i - 1 for i in want if 1 <= i <= total))
        out = []
        for i in idxs:
            txt = reader.pages[i].extract_text() or ""
            out.append({"page": i + 1, "text": txt, "n_chars": len(txt)})
        return out

    raise ImportError(
        "pdf_explore text extraction needs pypdfium2 or pypdf — run via "
        "`uv run scripts/pdf_explore.py …` (inline deps) or scripts/setup.sh."
    )


def render_pages(path, pages, dpi=200, out_dir=None):
    """Render the given 1-indexed pages to PNGs at `dpi`. Returns
    [{page, image_path}, ...]. Renders land under
    `.cache/pdf-explore/{sha8}-{mtime}/dpi{N}/p{NNN}.png` (keyed on
    path+mtime+dpi so a re-render at the same dpi, or after the PDF is
    edited, doesn't silently reuse stale PNGs). Pages already rendered
    on disk are skipped."""
    path = resolve_path(path)
    if not pages:
        raise ValueError("render: --pages is required (e.g. --pages 5 or 5,7-9)")
    pdfium = _try_pdfium()
    if pdfium is None:
        raise ImportError(
            "render needs pypdfium2 + pillow (PNG encoding). Run via "
            "`uv run scripts/pdf_explore.py render …` (inline deps) or "
            "scripts/setup.sh. pypdf cannot render pages."
        )
    try:
        import PIL.Image  # noqa: F401 — pypdfium2's to_pil() lazy-imports PIL
    except ImportError:
        raise ImportError(
            "render needs pillow for PNG encoding (pypdfium2's to_pil() "
            "lazy-imports PIL.Image). Run via `uv run …` (inline deps) or "
            "scripts/setup.sh."
        )
    abspath = os.path.abspath(path)
    mtime = os.stat(abspath).st_mtime_ns
    sha8 = hashlib.sha1(abspath.encode()).hexdigest()[:8]
    if out_dir is None:
        out_dir = os.path.join(os.getcwd(), ".cache", "pdf-explore",
                               f"{sha8}-{mtime}", f"dpi{int(dpi)}")
    os.makedirs(out_dir, exist_ok=True)
    doc = _pdfium_doc(abspath)
    out = []
    try:
        total = len(doc)
        idxs = sorted(i - 1 for i in pages if 1 <= i <= total)
        for i in idxs:
            ip = os.path.join(out_dir, f"p{i + 1:03d}.png")
            if not os.path.exists(ip):
                pg = doc[i]
                # PDF native is 72dpi → scale = desired/72.
                bmp = pg.render(scale=float(dpi) / 72.0)
                bmp.to_pil().save(ip)
            out.append({"page": i + 1, "image_path": ip})
    finally:
        doc.close()
    return out


# ── outline ─────────────────────────────────────────────────────────────────

_LEVEL_RE = re.compile(
    r"^\s*((?i:appendix|annex)\s+[A-Z0-9]+(?:\.\d+)*"
    r"|(?i:chapter)\s+\d+(?:\.\d+)*"
    r"|(?i:section)\s+\d+(?:\.\d+)*"
    r"|(?i:part)\s+[IVXLCivxlc\d]+(?:\.\d+)*"
    r"|[A-Z](?:\.\d+)*"
    r"|\d+(?:\.\d+)*)\b"
)
"""Matches a heading-ish token at line start: "3.2.1", "Section 4.1",
"Appendix A", "Chapter 2", "Part I". Level = 1 + dot-count of the matched
token (so "3.2.1" → level 3). Best-effort — a non-LLM fallback for PDFs
without an embedded outline; expect noise, filter when reading."""


def _outline_embedded(path):
    """Embedded bookmarks via pypdfium2 get_toc() — free and instant on
    LaTeX-compiled papers. Returns [{page, heading, level}, ...], or None
    to signal "couldn't try" so the regex fallback runs."""
    pdfium = _try_pdfium()
    if pdfium is None:
        return None
    doc = _pdfium_doc(path)
    try:
        toc = []
        for bm in doc.get_toc():
            dest = bm.get_dest()
            idx = dest.get_index() if dest else None
            # [level, title, 1-indexed page]; unresolvable destinations → 0
            toc.append([bm.level + 1, bm.get_title(),
                        (idx + 1) if idx is not None else 0])
    finally:
        doc.close()
    return [{"page": int(p), "heading": str(t), "level": int(lv)}
            for lv, t, p in toc if p > 0]


def _outline_regex(path):
    """No embedded outline — scan each page's text for numbered headings.
    Recall-complete but precision-noisy (every "see Section 3.2" matches);
    dedupe numbered headings to their last occurrence (a forward-ref keeps
    the section's own page), keep all unnumbered ("References", "Summary")."""
    pages = extract_text(path)
    out = []
    for p in pages:
        for line in p["text"].splitlines():
            s = line.strip()
            if not s or len(s) > 80 or s.endswith("."):
                continue  # headings are short and don't end with a period
            m = _LEVEL_RE.match(s)
            if not m:
                continue
            level = 1 + m.group(1).count(".")
            out.append({"page": p["page"], "heading": s, "level": level})
    last_page = {}
    for e in out:
        if _LEVEL_RE.match(e["heading"]):
            last_page[e["heading"]] = max(last_page.get(e["heading"], 0), e["page"])
    seen = set()
    deduped = []
    for e in out:
        k = (e["heading"], e["page"])
        if k in seen:
            continue
        if e["heading"] in last_page and e["page"] != last_page[e["heading"]]:
            continue
        seen.add(k)
        deduped.append(e)
    deduped.sort(key=lambda e: e["page"])
    return deduped


def get_outline(path):
    """[{page, heading, level}, ...]. Embedded bookmarks first (free);
    falls back to a regex scan of page text. Returns [] if neither yields
    anything — then navigate by per-page Agent map (see SKILL.md recipes)."""
    path = resolve_path(path)
    emb = _outline_embedded(path)
    if emb:
        return emb
    return _outline_regex(path)


def get_metadata(path):
    """Best-effort {title, author, ...} from whichever backend opens.
    pypdfium2 returns bytes keys/values; decode defensively."""
    pdfium = _try_pdfium()
    if pdfium is not None:
        doc = _pdfium_doc(path)
        try:
            try:
                md = doc.get_metadata_dict() or {}
            except Exception:
                return {}
            out = {}
            for k, v in md.items():
                kk = k.decode() if isinstance(k, (bytes, bytearray)) else str(k)
                vv = (v.decode("utf-8", "replace")
                      if isinstance(v, (bytes, bytearray)) else str(v))
                if vv and vv.strip():
                    out[kk] = vv
            return out
        finally:
            doc.close()
    PdfReader = _try_pypdf()
    if PdfReader is not None:
        try:
            m = PdfReader(path).metadata
            if m:
                d = dict(m)
                return {str(k).lstrip("/"): str(v) for k, v in d.items()
                        if str(v).strip()}
        except Exception:
            pass
    return {}


# ── subcommands ─────────────────────────────────────────────────────────────

def _format_pages(pages):
    return "".join(f"\n── page {p['page']} ──\n{p['text']}" for p in pages)


def _default_text_path(path):
    stem = os.path.splitext(os.path.basename(path))[0]
    return f"{stem}.txt"


def cmd_info(args):
    path = resolve_path(args.path)
    pages = extract_text(path)
    n = len(pages)
    mean = (sum(p["n_chars"] for p in pages) / n) if n else 0.0
    mode_hint = "image" if mean < PDF_AUTO_IMAGE_CHARS_THRESHOLD else "text"
    print(json.dumps({
        "path": os.path.abspath(path),
        "n_pages": n,
        "mean_chars_per_page": round(mean, 1),
        "has_outline": bool(get_outline(path)),
        "mode_hint": mode_hint,
        "metadata": get_metadata(path),
    }, ensure_ascii=False, indent=2))


def cmd_outline(args):
    path = resolve_path(args.path)
    outl = get_outline(path)
    if not outl:
        print("[pdf_explore] no embedded outline and no regex-detected "
              "headings — for navigation, fall back to per-page Agent "
              "summarization (see SKILL.md recipes).", file=sys.stderr)
    print(json.dumps(outl, ensure_ascii=False, indent=2))


def cmd_text(args):
    path = resolve_path(args.path)
    pages = parse_pages(args.pages)
    out = extract_text(path, pages=pages)
    # mode=auto: warn if the extracted range looks scanned (mean < 80
    # chars/page — the text layer is empty, so `render` + Read is the path).
    # Don't auto-switch: render produces images, not text.
    if args.mode == "auto" and out:
        mean = sum(p["n_chars"] for p in out) / len(out)
        if mean < PDF_AUTO_IMAGE_CHARS_THRESHOLD:
            print(f"[pdf_explore] ⚠ mean {mean:.0f} chars/page over {len(out)} "
                  f"page(s) — this looks scanned / image-only. Use `render "
                  f"--pages N --dpi 200` then Read the PNG; text extraction "
                  f"is empty here.", file=sys.stderr)
    # Write to a file by default — a full-paper extract is ~50K+ tokens and
    # would blow the Bash output buffer (and you'd Read it back anyway).
    # `--out -` sends to stdout for small / piped use.
    if args.out == "-":
        sys.stdout.write(_format_pages(out))
        return
    out_path = args.out or _default_text_path(path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(_format_pages(out))
    print(f"wrote {out_path} ({os.path.getsize(out_path):,} bytes, {len(out)} page(s))")


def cmd_render(args):
    path = resolve_path(args.path)
    pages = parse_pages(args.pages)
    if not pages:
        print("render: --pages is required (e.g. --pages 5 or 5,7-9)", file=sys.stderr)
        sys.exit(2)
    out = render_pages(path, pages, dpi=args.dpi, out_dir=args.out)
    for r in out:
        print(r["image_path"])
    print(f"[rendered {len(out)} page(s) at dpi={args.dpi}]", file=sys.stderr)


def cmd_crop(args):
    p = os.path.expanduser(args.image)
    if not os.path.exists(p):
        raise FileNotFoundError(f"crop: {args.image!r} not found")
    try:
        from PIL import Image
    except ImportError:
        raise ImportError("crop needs pillow — run via `uv run …` or setup.sh.")
    try:
        box = tuple(int(x) for x in args.box.split(","))
    except ValueError:
        raise ValueError("crop --box must be 4 ints: x0,y0,x1,y1")
    if len(box) != 4:
        raise ValueError("crop --box must be x0,y0,x1,y1 (4 ints)")
    out_path = args.out or "./crop.png"
    Image.open(p).crop(box).save(out_path)
    print(out_path)


def cmd_grep(args):
    path = resolve_path(args.path)
    pages = extract_text(path)
    q = args.query
    needle = q.lower() if args.ignore_case else q
    hits = []
    for p in pages:
        t = p["text"]
        hay = t.lower() if args.ignore_case else t
        idx = 0
        snippets = []
        while True:
            j = hay.find(needle, idx)
            if j < 0:
                break
            a = max(0, j - args.context)
            b = min(len(t), j + len(q) + args.context)
            # fold newlines so each snippet is one line in the JSON output
            snippets.append(t[a:b].replace("\n", " ⏎ "))
            idx = j + len(q)
        if snippets:
            hits.append({"page": p["page"], "n_hits": len(snippets),
                         "snippets": snippets})
    print(json.dumps(hits, ensure_ascii=False, indent=2))


# ── CLI ─────────────────────────────────────────────────────────────────────

def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="pdf_explore",
        description=("Stateless PDF navigation — parse once, write text/renders "
                     "to disk so you Read only what you need. No LLM calls; "
                     "scan/extract are Claude-orchestrated (see SKILL.md)."),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("info", help="page count, metadata, text-layer sanity, has-outline")
    p.add_argument("path")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("outline", help="table of contents (embedded bookmarks, else regex)")
    p.add_argument("path")
    p.set_defaults(func=cmd_outline)

    p = sub.add_parser("text", help="extract page text to a file (synthesize from this)")
    p.add_argument("path")
    p.add_argument("--pages", default=None, help="1-indexed pages/ranges, e.g. 5,21-25")
    p.add_argument("--mode", choices=["auto", "text"], default="auto",
                   help="auto warns if scanned; text suppresses the warning")
    p.add_argument("--out", default=None,
                   help="output file (default <stem>.txt; '-' for stdout)")
    p.set_defaults(func=cmd_text)

    p = sub.add_parser("render", help="render pages to PNG at dpi (for figures / scans)")
    p.add_argument("path")
    p.add_argument("--pages", required=True, help="1-indexed pages/ranges, e.g. 5 or 5,7-9")
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--out", default=None, help="output dir (default .cache/pdf-explore/…)")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("crop", help="crop a PNG region (read figures in detail)")
    p.add_argument("image", help="PNG path (e.g. from `render`)")
    p.add_argument("--box", required=True, help="x0,y0,x1,y1 pixels in the source PNG")
    p.add_argument("--out", default=None, help="output PNG (default ./crop.png)")
    p.set_defaults(func=cmd_crop)

    p = sub.add_parser("grep", help="keyword search across all pages → page hits + snippets")
    p.add_argument("path")
    p.add_argument("query")
    p.add_argument("--case-sensitive", action="store_true",
                   help="case-sensitive match (default: case-insensitive)")
    p.add_argument("--context", type=int, default=80, help="chars of context per hit")
    p.set_defaults(func=cmd_grep)

    args = ap.parse_args(argv)
    # honor --case-sensitive by flipping ignore_case
    args.ignore_case = not getattr(args, "case_sensitive", False)
    try:
        args.func(args)
    except (FileNotFoundError, ValueError, ImportError) as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
