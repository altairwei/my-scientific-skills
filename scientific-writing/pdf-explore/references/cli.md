# CLI reference — pdf_explore.py

Run as `uv run scripts/pdf_explore.py <subcommand> [flags]`. The inline
`# /// script` deps (pypdfium2, pillow, pypdf) auto-install on first call.

## Common

- **`--pages`** syntax (where accepted): comma-separated 1-indexed pages and
  `N-M` ranges, e.g. `5`, `5,7-9`, `5,21-25,62`. Bad tokens are skipped with
  a stderr warning. Omit for "all pages."
- **stdout vs file:** small JSON outputs (`info`, `outline`, `grep`) go to
  stdout; large text (`text`) goes to a `--out` file by default (a full-paper
  extract is ~50K+ tokens and would blow the Bash output buffer — `Read` the
  file instead). `text --out -` forces stdout for small / piped use.
- **stderr** carries warnings (scanned-doc hint, no-outline hint, bad page
  tokens, render summary) — separate from the stdout JSON you parse.

## info

```bash
uv run scripts/pdf_explore.py info PATH
```

First look. Stdout JSON:
```json
{ "path": "/abs/paper.pdf", "n_pages": 32, "mean_chars_per_page": 1840.5,
  "has_outline": true, "mode_hint": "text", "metadata": {"Title": "..."} }
```
- `mean_chars_per_page` < 80 → `mode_hint: "image"` (scanned; use `render`).
- `has_outline`: whether `outline` will yield anything.

## outline

```bash
uv run scripts/pdf_explore.py outline PATH
```

Stdout JSON `[{page, heading, level}, ...]` in page order. `level` = 1 +
dot-count of the heading's number (`3.2.1` → 3). Embedded bookmarks first
(free, via pypdfium2 `get_toc()`); falls back to a regex scan of page text
(noisier — every "see Section 3.2" can match). If empty, stderr suggests
per-page Agent map (recipes §4). No `--pages` (whole-doc operation).

## text

```bash
uv run scripts/pdf_explore.py text PATH [--pages 5,21-25] [--mode auto|text] [--out FILE]
```

Extract page text (with `── page N ──` markers) to `--out` (default
`<stem>.txt`; `--out -` for stdout). Prints `wrote <path> (<bytes>, <n>
page(s))`. `--mode auto` (default) warns to stderr if the range averages
<80 chars/page (scanned → use `render`); `--mode text` suppresses the
warning. Backends: pypdfium2 text layer, else pypdf `extract_text()`.

## render

```bash
uv run scripts/pdf_explore.py render PATH --pages PAGES [--dpi 200] [--out DIR]
```

Render the given pages to PNGs at `--dpi` (default 200). `--pages` is
**required**. `--out` defaults to `.cache/pdf-explore/{sha8}-{mtime}/dpi{N}/`
under the cwd — keyed on path+mtime+dpi, so a re-render at the same dpi
skips work; editing the PDF (mtime changes) invalidates. Prints one PNG
path per line to stdout; a summary to stderr. Requires pypdfium2 + pillow
(pypdf can't render — clear error if either is missing).

## crop

```bash
uv run scripts/pdf_explore.py crop IMAGE --box x0,y0,x1,y1 [--out PNG]
```

Crop a PNG region via PIL. `--box` is 4 ints (pixels in the source PNG).
`--out` defaults to `./crop.png`. Prints the output path. Use on a
`render`-produced PNG to read a figure region at full resolution (the
attach pipeline downsamples full pages). Requires pillow.

## grep

```bash
uv run scripts/pdf_explore.py grep PATH QUERY [--case-sensitive] [--context 80]
```

Keyword search across all pages. Default case-insensitive; `--case-sensitive`
to match exactly. `--context` (default 80) chars of context around each hit.
Stdout JSON `[{page, n_hits, snippets}]` (each snippet is one line, newlines
folded to `⏎`). For repeated queries on one PDF, `text --out full.txt` once
then `rg` the file is cheaper (each `grep` re-parses).

## Error & exit behavior

- Missing file / bad `--box` / password-protected PDF → message to stderr, exit 1.
- Password-protected PDFs raise with a `qpdf --decrypt --password=... in.pdf out.pdf` recipe (or `pypdfium2.PdfDocument(path, password=pw)`).
- Missing deps (pypdfium2/pillow/pypdf) → message to stderr, exit 1 — run via `uv run …` (inline deps auto-install) or `scripts/setup.sh`.

## Backends & licensing

- **pypdfium2** (Apache-2.0 / BSD-3-Clause) — primary; text extraction and page rendering.
- **pypdf** (BSD-3-Clause) — text-only fallback when pypdfium2 isn't installed; cannot render.
- **PyMuPDF / fitz is intentionally unsupported** — AGPL-3.0. pypdfium2 already covers text + render; installing fitz will not activate a fallback path. (If you need fitz for a specific edge case, add a branch yourself, but mind AGPL's source-sharing terms if you embed it in a network-accessible service.)
