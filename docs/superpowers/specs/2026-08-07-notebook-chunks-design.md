# Notebook chunk parsing + selective execution — Design Spec

**Date:** 2026-08-07
**Status:** Design — pending implementation plan
**Skill name:** `interactive-repl` (extension to the existing skill)
**Category:** `data-science/`

---

## 1. Problem & goal

The `interactive-repl` skill ships a persistent R/Python REPL and a `run_code(session, code)`
tool, but its handling of notebook files (`.Rmd`/`.qmd`/`.ipynb`) is one hand-waved line in
`SKILL.md`:

> For notebook/qmd workflows, extract a chunk's code (read the chunk body or `knitr::purl`)
> and pass it to `run_code`.

So the agent hand-extracts chunks every time — re-rolling a regex/fence/JSON parser per call,
which is error-prone (markdown fences, `#|` Quarto cell options, `.ipynb` JSON nesting,
`eval=FALSE`/`purl=FALSE` semantics). There is no list-chunks capability and no workflow
guidance. A human in RStudio / VSCode / Jupyter can click a chunk and run it, run a range, or
run-all-above; the agent cannot match that workflow today.

**Goal:** add a parse-and-select layer on top of the existing `run_code`, so the agent can list
the code chunks of a notebook and selectively run one or a range in the persistent session — in
dependency order, respecting chunk options, routing each chunk to the matching REPL by
language. The shipped tooling is original and self-contained; it does not reference
`openclaw-science` or any external plugin.

## 2. Reference: r-cell's chunk tool (provenance)

The user's `external/r-cell/r-cell.sh` already solves this for `.qmd` (R-only):

- `r-cell.sh chunks FILE.QMD` — list chunk labels. No session needed. Delegates parsing to
  `r-split.R`.
- `r-cell.sh run --chunk LABEL:F.QMD` — extract one chunk by label, run it in the persistent
  tmux+R session.

`r-split.R` calls `knitr::purl()` to tangle the document into R code, then re-splits on purl's
`## ----label----` separators. It honours `purl=FALSE`/`eval=FALSE`, skips `teardown`/`cleanup`
chunks, and gives unnamed chunks sequential labels.

This spec generalizes that pattern to `.Rmd`/`.qmd`/`.ipynb`, routes chunks by language to the
matching REPL, and adapts it to the MCP-server (not tmux) execution model.

## 3. Goals & non-goals

**Goals (v1):**

- Parse `.Rmd`/`.qmd`/`.ipynb` into an ordered list of code chunks with metadata: index, label,
  language, code, `eval`, `include`.
- A read-only CLI to list and extract chunks (no session needed).
- An MCP `run_chunk(session, file, selector)` tool on both `python-repl` and `r-repl` servers
  that parses, resolves a selector (label / index / range), and runs the matching chunks in
  notebook order via the existing `_call_worker`.
- Cross-language routing: each server runs only its own language's chunks; the rest are
  reported as `skipped` with a routing hint.
- Respect chunk options: `purl=FALSE` excluded from the list; `eval=FALSE` skipped on run;
  `include=FALSE` informational (still runs).
- Workflow guidance: a new `references/notebook-iteration.md` and a `SKILL.md` notebook section.

**Non-goals (deferred — see §13):** writing outputs back into the notebook (this is REPL
iteration, not rendering — use `quarto render` / `jupyter nbconvert --execute` for headless
render); a `force` flag to run `eval=FALSE` chunks (the agent can extract via CLI +
`run_code`); `knitr::purl()` as the primary parser (kept as an escape hatch — see §6);
`--lang` filter on the CLI; streaming per-chunk output mid-run.

## 4. Architecture: CLI list + MCP run_chunk

The skill already has `run_code(session, code)` for execution. This feature is purely the
parse + select layer on top. Of three wirings considered:

- **A. CLI only** — `notebook_chunks.py` lists + extracts; agent calls it via Bash, then
  `run_code`. Simplest, but two tool calls per chunk and the agent holds the chunk list.
- **B. Full MCP** — `list_chunks` + `run_chunk` as MCP tools. Uniform, but `list_chunks`
  needs a server round-trip despite needing no session.
- **C. CLI list + MCP run_chunk (chosen)** — `notebook_chunks.py` for the cheap, stateless
  list/extract path (no session, like r-cell's `chunks`); `run_chunk` MCP tool for the one-call
  run path (matches r-cell's one-command `run --chunk` ergonomics). Shared parser module.

**Chosen: C.** Best ergonomics per unit of surface. The CLI needs no session and is cheap to
inspect; `run_chunk` gives GUI-like one-call execution and composes with the existing
`_call_worker` / session pool.

## 5. Components / file layout

```
data-science/interactive-repl/
├── scripts/
│   ├── _chunk_parser.py          # NEW — shared parser (pure stdlib): file → [Chunk]
│   ├── notebook_chunks.py        # NEW — CLI: list / extract chunks (no session)
│   ├── python_repl_server.py     # MODIFIED — add run_chunk tool; import _chunk_parser
│   ├── r_repl_server.py         # MODIFIED — add run_chunk tool; import _chunk_parser
│   └── (existing files unchanged)
├── references/
│   └── notebook-iteration.md     # NEW — workflow guidance
├── tests/
│   ├── fixtures/
│   │   ├── notebook.Rmd          # NEW — synthetic, covers fence + header opts
│   │   ├── notebook.qmd          # NEW — synthetic, covers #| Quarto options
│   │   └── notebook.ipynb        # NEW — synthetic, mixed-language cells
│   ├── test_chunk_parser.py      # NEW
│   ├── test_notebook_cli.py      # NEW
│   ├── test_python_server.py     # MODIFIED — +run_chunk tests
│   └── test_r_server.py          # MODIFIED — +run_chunk tests
└── SKILL.md                      # MODIFIED — notebook section, tools list, deep-docs pointer
```

The parser module is named `_chunk_parser.py` (not the vague `_notebook.py`) — it states what
the module *does*. The `_` prefix follows the existing `_common.py` convention for shared
sibling modules imported across the servers and the CLI.

## 6. The parser — `scripts/_chunk_parser.py`

Pure-stdlib module (no R, no `pydantic`, no external deps) so it is testable in isolation and
the CLI runs anywhere with `uv run` / `python3`.

```python
@dataclass
class Chunk:
    index: int          # 1-based, notebook-global
    label: str          # knitr label, or "unnamed-<index>"
    language: str       # 'r' | 'python' | <engine>
    code: str           # chunk body, stripped of #| option lines
    eval: bool          # False if eval=FALSE / #| eval: false
    include: bool       # False if include=FALSE (informational; we still run)
    source: str         # absolute path of the notebook

def parse_notebook(path: str) -> list[Chunk]:
    """Dispatch by extension. Raise ValueError on unknown ext or no chunks found."""
```

### `.ipynb` → `_parse_ipynb`

`json.load` the file, iterate `cells`, keep `cell_type == "code"`, join the `source` (a list of
lines) into `code`. Language from `metadata.kernelspec.language` (fallback `"python"`). All
code cells have `eval=True` (`.ipynb` has no `eval=FALSE` semantic); honour a
`"skip-execution"` cell tag if present (set `eval=False`).

### `.Rmd` / `.qmd` → `_parse_rmd`

Line-based fence parser:

- **Opening fence:** a line matching `^```{(\w+)\s*([^,}]*)` → engine = group 1
  (`r`/`python`/…), label = group 2 (may be empty → `unnamed-<index>`).
- **Body:** lines until a closing fence `^```\s*$`.
- **`#|` Quarto option lines:** stripped from the body. Parse `eval`/`include`/`purl` from
  both the fence header (`{r label, eval=FALSE}`) and `#|` lines, accepting both YAML
  (`#| eval: false`) and knitr (`#| eval=FALSE`) spellings.
- `purl=FALSE` → **excluded from the list entirely** (knitr semantics).
- `eval=FALSE` → kept, `eval=False` (run_chunk skips it; the CLI still lists it, marked).
- `include=FALSE` → `include=False` but still runnable. We surface output (documented
  deviation from knitr's hide-output — the REPL is transparent).
- Unnamed chunks → `unnamed-<index>`.

### Honest limitation

The fence-parser is best-effort: a literal triple-backtick *inside* a chunk body (rare) can
confuse it. `knitr::purl()` is the gold standard but needs R, which the `python-repl` server
does not have, so the parser is pure-Python to keep both servers symmetric and the CLI
dependency-free. Documented in `references/notebook-iteration.md`, with the escape hatch: for
100% knitr fidelity the agent can `run_code` a one-liner
`knitr::purl("file.qmd", output=…)` on `r-repl` and read the tangled file.

## 7. The CLI — `scripts/notebook_chunks.py`

Read-only, no session, deterministic. Run via `uv run scripts/notebook_chunks.py …`
(`uv` is already required by the skill).

```
notebook_chunks.py FILE             # default: human table — index, label, lang, eval, lines
notebook_chunks.py FILE --json       # JSON array of full Chunk descriptors (incl. code)
notebook_chunks.py FILE --chunk SEL  # print that chunk's code to stdout
notebook_chunks.py FILE --chunks RNG # print concatenated code for a range
```

`SEL` = label (`extract`) or 1-based index (`3`). `RNG` = `3-7` / `3-` (to end) / `1-5`. The
agent uses `--json` to inspect code before running, `--chunk`/`--chunks` to feed `run_code`
when it wants full control, and `run_chunk` for the one-call path.

## 8. The MCP tool — `run_chunk` (on both servers)

```python
@mcp.tool()
async def run_chunk(session: str, file: str, selector: str) -> RunChunkResult:
    """Run one chunk (or a range) from a .Rmd/.qmd/.ipynb notebook in the session.
    selector = label | index | 'N-M' | 'N-'. Parses, resolves, runs each chunk in
    notebook order via the session worker. Skips eval=FALSE and wrong-language chunks
    (listed in `skipped`). Stops on first error (dependency order)."""
```

### `RunChunkResult` (Pydantic; returned as `structured_content`)

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
```

### Behavior

1. `chunks = _chunk_parser.parse_notebook(file)` — the agent should pass an **absolute**
   `file` path (the server's cwd may differ from the agent's — same convention as
   `source()`/`read.csv()` in `SKILL.md`). On `FileNotFoundError` / `ValueError` (unknown
   ext / no chunks), return `RunChunkResult` with `error` set and nothing ran.
2. Resolve the selector → an ordered list of chunks. Resolution order: `^\d+-\d*$`
   (e.g. `3-7`, `3-`) → range; `^\d+$` (e.g. `3`) → 1-based index; otherwise → label match.
   (Numeric selectors take precedence over label — a chunk labelled purely with digits is
   pathological; the agent reaches it via the CLI's `--chunk` label path if ever needed.)
   On no match, return `error="chunk '<sel>' not found. Available: <labels> (indices 1-N)"`
   (r-split.R-style helpful message).
3. Partition: `eval=False` → `skipped` (reason `"eval=FALSE"`); `language != this server's
   language` → `skipped` (reason `"language=<lang>, use <other>-repl"`). The parser
   normalizes the engine to lowercase; `python-repl` runs `language == "python"`, `r-repl`
   runs `language == "r"`. Chunks in other engines (Julia, bash, …) are skipped with the
   same routing reason.
4. Run the remaining chunks **in notebook (index) order** via `_call_worker(session,
   chunk.code)`. Concatenate `stdout`/`stderr`, merge `plots`, OR `truncated`/`degraded` across
   chunks. **Stop on first error** (`_call_worker` returns `error` set): set `error` +
   `failed_chunk`, return partial results. Notebook dependency semantics — a failed chunk breaks
   the chain; later chunks are not run.
5. Aggregate into `RunChunkResult` with `ran` = the chunks that executed.

Both servers get an identical `run_chunk`; each runs only chunks matching its own language.
For a mixed `.qmd` (R + Python chunks), the agent calls `run_chunk` on `r-repl` (Python chunks
appear in `skipped`) and on `python-repl` (R chunks appear in `skipped`).

`run_chunk` reuses the existing session pool and `_call_worker` — it does **not** duplicate
worker logic. A `worker died` mid-chunk propagates exactly as `run_code` (the agent calls
`restart` and re-runs).

## 9. Selectors & execution semantics

| Selector | Meaning |
|---|---|
| `extract` | chunk with label `extract` |
| `3` | chunk at 1-based index 3 |
| `3-7` | chunks 3 through 7, inclusive, in order |
| `3-` | from chunk 3 to the end |

- Chunks always run in **notebook (index) order**, even for a range — respects dependencies.
- `eval=FALSE` → skipped (respected). `purl=FALSE` → never listed. `include=FALSE` → runs
  (informational only).
- Language mismatch → skipped with a routing hint (`"language=r, use r-repl"`).
- Selector not found → error lists the available labels and the index range.
- Read-only on the notebook file: `run_chunk` and the CLI never write to it. Outputs (plots)
  go to the existing plot dir under `CLAUDE_PLUGIN_DATA` + `Read`, same as `run_code`.

## 10. Error handling

- File not found / unreadable → `error="file not found: <path>"`, nothing ran.
- Unknown extension → `error="unsupported file type: .<ext> (expected .Rmd/.qmd/.ipynb)"`.
- No chunks found → `error="no code chunks found in <path>"`.
- Selector not found → `error="chunk '<sel>' not found. Available: <labels> (indices 1-N)"`.
- Chunk errors during run → stop, return partial `stdout`/`stderr`/`plots` + `error` +
  `failed_chunk`. Session stays usable.
- `worker died` mid-chunk → propagate (same as `run_code`); agent calls `restart` + re-runs.

## 11. SKILL.md & reference guidance

**New `references/notebook-iteration.md`** — the workflow:

1. `notebook_chunks.py FILE` → see chunks (labels, languages, eval flags).
2. `run_chunk(session, FILE, selector)` → run one or a range; check `ran` / `skipped` /
   `error`.
3. If a chunk errors, **`Edit` the notebook file** to fix it, then `run_chunk` again — state
   persists, do not restart between chunks.
4. Plots auto-save to disk + `Read` (same as `run_code`).
5. Cross-language qmd/ipynb: R chunks → `r-repl`, Python → `python-repl`; the `skipped` field
   tells you what to route.
6. **Not for headless render** — to execute a whole notebook and write outputs back, use
   `quarto render` / `jupyter nbconvert --execute`. This skill is REPL iteration: read-only on
   the file, outputs to disk.
7. Limitation + escape hatch: the fence-parser is best-effort; for knitr fidelity use
   `knitr::purl()` via `run_code` on `r-repl`.

**SKILL.md** changes:

- New `## Notebooks (.Rmd/.qmd/.ipynb)` section (one paragraph + pointer to
  `references/notebook-iteration.md`).
- Add `run_chunk(session, file, selector)` to the tools list.
- Add `notebook_chunks.py` to the scripts mention.
- Add `references/notebook-iteration.md` to "Deep docs".
- **Replace the hand-wave at SKILL.md:86–87** ("extract a chunk's code… and pass it to
  `run_code`") with a pointer to `run_chunk` / `notebook_chunks.py`.

## 12. Testing (TDD)

Per the repo's TDD discipline: write a failing test → run (red) → implement → run (green) →
commit.

- `test_chunk_parser.py` — fixtures for `.Rmd`/`.qmd`/`.ipynb`:
  - engine + label parsing (named and unnamed chunks);
  - `#| eval: false` (YAML) and `{r label, eval=FALSE}` (header);
  - `include=FALSE` (informational), `purl=FALSE` (excluded);
  - language detection — R, Python, mixed;
  - `.ipynb` kernelspec language + code-cell filtering + `skip-execution` tag;
  - no-chunks error, unknown-extension error.
- `test_notebook_cli.py` — default table, `--json`, `--chunk` by label + index, `--chunks`
  range, file-not-found, bad selector.
- `test_python_server.py` + `test_r_server.py` (extend) — `run_chunk` by label/index/range;
  `eval=FALSE` skip; wrong-language skip; chunk-not-found error; stop-on-first-error
  (partial results + `failed_chunk`); `worker died` propagation.

## 13. Scope: v1 vs deferred

**In v1:** the parser, the CLI (list/extract), `run_chunk` on both servers, cross-language
routing, chunk-option semantics (`eval`/`include`/`purl`), the reference + SKILL.md guidance,
and the test suite.

**Deferred (YAGNI for v1):**

- Writing outputs back into the notebook (render, not iterate — use `quarto render` /
  `nbconvert --execute`).
- A `force` flag to run `eval=FALSE` chunks (agent uses CLI + `run_code`).
- `knitr::purl()` as the primary parser (escape hatch only — see §6).
- `--lang` filter on the CLI.
- `-N` (from-start) selector sugar (use `1-N`).
- Streaming per-chunk output mid-run.
- Markdown/narrative-cell extraction (agent `Read`s the file directly for narrative).

## 14. Risks & open questions

- **Fence-parser robustness** — the chief risk. Mitigated by documenting the limitation and
  the `knitr::purl()` escape hatch. Real notebooks rarely nest triple-backticks inside code
  chunks; if this proves wrong in practice, v2 can make `knitr::purl()` the primary path on
  `r-repl` (which has R) and keep the fence-parser for `python-repl` + `.ipynb`.
- **`include=FALSE` semantics** — we run these and surface output (deviation from knitr).
  Revisit if it floods the agent with setup-chunk clutter; a v1.1 fix is to suppress stdout
  for `include=False` chunks while still running them.
- **Large notebooks in context** — `notebook_chunks.py --json` on a notebook with many large
  chunks could be heavy. Mitigation: the default table is compact (no code); the agent only
  requests `--json` / `--chunk` for the chunk it wants.

## 15. Provenance

The chunk-list-and-run-by-label pattern is adapted from the user's `external/r-cell/r-cell.sh`
(`chunks` + `run --chunk`) and `r-split.R` (`knitr::purl()`-based splitting, `## ----label----`
re-splitting, `purl=FALSE`/`eval=FALSE`/`teardown` handling). These are credited here for
design traceability; the shipped `_chunk_parser.py`, `notebook_chunks.py`, and the `run_chunk`
tools are original and self-contained, and do not reference `openclaw-science` or any external
plugin. Unlike `r-split.R`, this parser is pure-Python (no R dependency) so both MCP servers
and the CLI can parse all three formats, and execution routes by detected language rather than
assuming R.
