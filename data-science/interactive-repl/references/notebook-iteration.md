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
chunk in notebook order. `selector` = label (`extract`), index (`3`), range (`3-7`), open
range (`3-` = to end), run-above (`^extract` = chunks 1..extract — "Run All Above"), or
run-from (`extract^` = chunks extract..end). Returns `{stdout, stderr, error, plots, ran,
skipped, failed_chunk}`.

- `ran` — chunks that executed (index/label/language).
- `skipped` — chunks not run, with a reason: `eval=FALSE` or `language=<lang>, use <other>-repl`.
- `failed_chunk` — the chunk that errored, if `error` is set. Later chunks are not run.

## Cross-language routing

A `.qmd` or `.ipynb` can mix R and Python chunks. `run_chunk` on **r-repl** runs only
`language == "r"` chunks; on **python-repl** only `language == "python"`. The rest appear
in `skipped` with a routing hint. For a mixed notebook, call `run_chunk` on each server:
R chunks on `r-repl`, Python chunks on `python-repl`.

## Paths: absolute `file`, chunk-relative everything else

`run_chunk`'s `file` arg must be absolute (the server's cwd may differ from yours). But
`run_chunk` also sets the **session cwd to the notebook's dir** before running the chunks,
so relative paths *inside* the chunks resolve relative to the notebook —
`source("shared-config.R")`, `read.csv("data.csv")`, `readRenviron("../../.Renviron")`
all work as they would in the GUI. (This is r-cell's `cd analysis/phenotypes` lesson.)
Subsequent `run_code` calls inherit this cwd; use `setwd()` / `os.chdir()` to change it.

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
