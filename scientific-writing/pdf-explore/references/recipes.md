# Recipes — pdf-explore

Concrete workflows. Adapted from the original pdf-explore skill for the
stateless-script + Agent-subagent architecture (no `host.llm`). Replace
`scripts/pdf_explore.py` with the absolute path in your install, or rely on
`uv run` resolving the script by path.

Throughout, `PE` = `uv run scripts/pdf_explore.py`.

## 1. Pull the sections you need as persistent text (synthesis)

For "summarize the methods" / "compare section 3 and section 5" / anything
where the answer draws on several page ranges at once, do **not** read the
ranges one `Read(pages=[...])` call at a time — each call's vision pages
don't survive past the next turn, and you'll loop re-reading them. Pull
**all** the pages in one script call, then `Read` the file:

```bash
# find the page numbers from `outline` (recipe 2) or the paper's TOC first
PE text paper.pdf --pages 5,21-25,62-64,124-126 --out sections.txt
```

Then `Read sections.txt` (use `offset`/`limit` if it's over ~100KB). Write
the answer from that. **Don't `print` page text to stdout** — the script
writes to a file by default precisely because a full chapter (~50K+ tokens)
would blow the Bash output buffer, and you'd `Read` it back anyway. For a
quick look at ≤5 pages, `--out -` (stdout) is fine.

~800 tokens/page of text vs ~4000 as vision — paid once.

## 2. Navigate by outline (try this first)

```bash
PE outline paper.pdf
# → [{page, heading, level}, ...] JSON
```

Free and instant when the PDF has an embedded outline (most LaTeX-compiled
papers do). Falls back to a regex scan of page text for numbered headings
(`1 Introduction`, `3.2 Methods`, `Appendix A`) — noisier, filter when
reading. If it returns `[]`, the doc has no usable structure → fall back to
recipe 4 (per-page Agent map).

Then `text --pages <the section you want> --out sec.txt` → `Read sec.txt`.

## 3. Find the pages relevant to a query

**Keyword** (instant, cached on the text layer):

```bash
PE grep paper.pdf "Harmony"            # case-insensitive by default
# → [{page, n_hits, snippets}]
```

**Semantic** ("where are the limitations discussed") — keywords won't find
that. Use recipe 4 (Agent fan-out over per-range text files) and ask each
subagent which of its pages discuss the query.

## 4. Map every page (Agent fan-out)

For unstructured docs (transcripts, slide dumps, multi-doc compilations) or
a free-text question of every page: write per-range text files, then
dispatch one haiku subagent per range, each summarizing its pages. 100
pages → 5 files × 20 pages → 5 haiku subagents at ~16K input + ~2K output
each; the parent holds only the 5 returned summaries (~10K tokens).

```bash
# 1. write the ranges (one parse per range — `text` only touches those pages)
for r in "1-20" "21-40" "41-60" "61-80" "81-100"; do
  PE text transcript.pdf --pages "$r" --out "pages_${r}.txt"
done
```

Then, in **one message**, dispatch 5 parallel `Agent({model:"haiku"})`
calls — each prompt: *"Read ./pages_01-20.txt and summarize each page in 2
sentences. Return a JSON list of {page, summary}."* Merge. Replaces the
original's `pdf_map` LLM fan-out.

## 5. Structured extraction (Agent fan-out)

"List every dataset / citation / figure / accession number mentioned
anywhere in this paper." Same per-range-file pattern, but the subagent
prompt asks for a JSON-shaped extraction:

> Read ./pages_01-20.txt. Extract every dataset on which results are
> actually reported on these pages (in a table or the text), **not**
> datasets merely cited or mentioned. Return `[{page, name, role}]` as JSON.

**Put the inclusion criterion in the prompt** ("reported on", not
"mentioned") — the subagent applies it for you. Merge + dedupe the
per-range lists. The original's guidance carries over: the sweep already
read every page (via the text files), so **don't follow it with
`Read(pages=[...])` vision loads to "check for missed items"** — that
re-spends the tokens the text-extract just saved. If you doubt a specific
hit, `text --pages <that page> --out -` and re-check the text (cheap,
cached on disk). Call budget for an exhaustive-extraction job: N range
writes + N subagents + one merge — not a vision page in sight.

## 6. Read a figure in detail

A full rendered page is too low-resolution to read small axis labels or
legend text off a dense multi-panel figure — the attach pipeline
downsamples. **Render the page at high DPI, crop the figure, then `Read`
the crop.** The crop is both more legible *and* cheaper (~400 vision
tokens vs ~1600 for the full page).

```bash
# 1. render the figure's page at dpi=200 — high enough to crop into
PE render paper.pdf --pages 5 --dpi 200
# → .cache/pdf-explore/<sha>-<mtime>/dpi200/p005.png

# 2. crop the figure region (pixels in the dpi=200 render). Attach the
#    full page once to locate the figure, OR go straight to a crop if
#    the caption/position tells you where:
PE crop .cache/pdf-explore/.../p005.png --box 120,80,740,520 --out fig5.png
# 3. Read fig5.png
```

Crop one panel at a time for multi-panel figures. Always crop from the
`.cache/` render, not from a previously attached (downsampled) view.

## 7. Grep a keyword

```bash
PE grep paper.pdf "Harmony" --context 120
# → [{page, n_hits, snippets}]  — each snippet is ±120 chars around a hit
```

For *repeated* queries on one PDF, `text --out full.txt` once then `rg
"Harmony" full.txt` is cheaper than re-parsing per `grep` (each `grep` is
a fresh parse). Use `grep` for a one-off, `text`+`rg` for a session.
