# plotly-interactive-figures Skill — Design

**Date:** 2026-08-15
**Status:** Approved (brainstorming phase) → ready for implementation plan
**Approach:** import-only audit module + four references; spec-primary verification with Kaleido escalation; `.ipynb` notebook deliverable

## Goal

A skill that lets an LLM agent **with no visual capability** make, verify, and **debug** Plotly interactive figures — diagnosing plotting problems through the figure's transparent JSON spec instead of seeing the render. The primary deliverable to the user is a **Jupyter notebook (`.ipynb`)** organizing multiple figures with markdown commentary.

The core insight: a Plotly `Figure` is a transparent JSON spec tree — `to_dict()`/`to_json()` exposes the *skeleton* (only what you set), and `full_figure_for_development()` exposes the *full* spec after Plotly.js fills in defaults (axis ranges, `cliponaxis`, tick layout, …). A vision-less agent can inspect and debug this structure without ever rendering, turning visual problems into data-structure problems. This sidesteps the unreliable save-PNG-and-`Read` loop matplotlib forces — `figure-style` and `interactive-repl` both `Read` PNGs but acknowledge (in `plot-iteration.md`) that looking is fallible and `Read` can return "Unsupported Image." For Plotly, the spec is the primary channel and vision is an optional escalation, not the default.

## Non-goals

- **matplotlib/seaborn publication figures → `figure-style`.** That skill owns the render-then-verify-via-PNG-crops loop and assumes the agent can `Read` PNGs. This skill is Plotly-specific.
- **Multi-panel publication figure arcs → `figure-composer` / `paper-narrative`.**
- **Persistent REPL / session mechanics / running cells → `interactive-repl`.** This skill is tool-agnostic: it works with the `repl` MCP, the user's own Jupyter, or a plain script. It bundles **no** MCP server.
- **Data prep / EDA → `exploratory-data-analysis`.**
- **`dash_bio` genomics-specific charts** (interactive Manhattan/QQ via the `dash_bio` package — a separate, heavier Dash-ecosystem dependency, not `px`). Deferred to a later tier; v1 is standard statistical `px` charts only.
- **Real-time interaction monitoring** (hover/click/selection callbacks). `FigureWidget` callbacks are technically possible but incompatible with the conversational request/response agent model.
- **Aesthetic judgment** (color harmony, true overlap perception, contrast). JSON cannot decide these; they go to the Kaleido→`Read` escalation or the user-as-eyes loop. Acknowledged honestly, not solved.

## The core: debugging without vision (重点)

Three introspection depths, escalating only when the shallower one cannot settle the problem:

| Depth | API | Reveals | Dep |
|---|---|---|---|
| **Skeleton** | `fig.to_dict()` / `fig.to_json()` / `print(fig)` / `fig.show("json")` | only the attributes you set | pure plotly, zero deps |
| **Full spec** | `fig.full_figure_for_development(warn=False)` | all Plotly.js-computed defaults (axis ranges, `cliponaxis`, tick layout, …) — the root-cause finder | Kaleido |
| **Vision (last resort)** | `fig.write_image(...)` → `Read` the PNG | the perceptual layer (color, real overlap, contrast) | Kaleido; if `Read` returns "Unsupported Image", fall back to numerical verification (`interactive-repl` `plot-iteration.md`) |

**Canonical case study** (straight from the official `figure-introspection` doc): text labels clipped at the axis edge → `full_figure_for_development()` reveals `cliponaxis=True` → `fig.update_traces(cliponaxis=False, textposition="top right")` fixes it. This *is* the symptom→JSON→fix loop, demonstrated by the source.

**Debugging loop:**

1. **Structural pre-check** — `pa.audit(fig)` over the `to_dict()` skeleton: catch empty traces, off-canvas legends, missing hover/color, `cliponaxis`-on-text, log-axis-with-zero, etc. Fix until no errors.
2. **Deliver** — `fig.show()` interactive, or embed in the notebook.
3. **Diagnose** — if the user reports a visual symptom, map it via `symptom-prescription.md` to a JSON checkpoint → surgical `update_traces`/`update_layout` fix.
4. **Escalate** — to full spec (`full_figure_for_development`) or vision (`write_image`→`Read`) only for the residual perceptual cases the skeleton cannot settle.

**No silent caps:** when the audit cannot check a class of problem without Kaleido (e.g. a true color clash), it says so out loud rather than implying the figure is verified.

## The deliverable: a Jupyter notebook (`.ipynb`)

The skill's primary output to the user. The agent assembles (via `nbformat`) a notebook that:

- holds **multiple Plotly figures in code cells** (`px`-first; `graph_objects` only when `px` cannot express it).
- carries **markdown commentary cells** — the agent's pre-computed data insights, per-figure notes, attention points, and diagnostic reasoning (the vision-less agent's "eyes," conveyed as text to the user).
- is **executed to embed outputs** (`jupyter nbconvert --execute --to notebook --inplace` — headless; Plotly figures embed as interactive HTML with no display needed) so the user opens a notebook with the figures already rendered. The agent iterates and audits figures in-session via `interactive-repl` first; the final notebook is assembled with `nbformat` then executed with `nbconvert`.
- is **written locally with `Write`** (the repo's no-upload convention — never published).

Deliverable-time deps: `nbformat` + `nbconvert` (+ `jupyter` core) on top of `plotly`. The audit itself needs only `plotly` (+ optional `pandas` for `df`-based checks); Kaleido only on the documented escalation path.

## Architecture

```
data-science/plotly-interactive-figures/
├── SKILL.md                  # the protocol: prep(→EDA) → build(px-first) → audit → deliver(.ipynb) → diagnose; Kaleido escalation
├── scripts/
│   └── plotly_audit.py       # import-only: audit(fig_or_spec, df=None) -> list[Finding]
└── references/
    ├── debugging-without-vision.md   # three-depth methodology + cliponaxis case + escalation ladder
    ├── symptom-prescription.md       # symptom → JSON checkpoint → fix code → official-doc URL
    ├── px-patterns.md                # one canonical px pattern per chart family, grounded in docs, audited
    └── notebook-delivery.md          # nbformat assembly + execute-to-embed-outputs
```

### Marketplace registration

Add `./data-science/plotly-interactive-figures` to the `data-science` plugin's `skills` list in `.claude-plugin/marketplace.json`. Add a row to `README.md`'s `data-science` table. **No `mcpServers`** — this is a tool-agnostic, pure-script skill (like `figure-style`), not an MCP skill.

### `description` frontmatter (draft)

```yaml
description: Make, verify, and debug Plotly interactive figures when you (the agent)
  have no visual capability — diagnose problems through the figure's JSON spec
  (to_dict/to_json, full_figure_for_development) instead of seeing the render. Deliver
  a .ipynb notebook of figures + markdown commentary. Triggers on interactive
  plotly/plotly-express charts, hover/zoom, or "this plotly looks wrong". Route
  matplotlib/publication figures to figure-style.
```

~70 tokens (trimmed from ~95 during implementation to stay under the ~100-token guideline; verified with count-skill-tokens.py). Includes "no visual capability" as a triggering context (this skill is **for** vision-less LLMs — the user's explicit ask) and the "looks wrong" symptom trigger; routes matplotlib → `figure-style`.

## The audit module (`scripts/plotly_audit.py`)

```python
# import-only, like figure_style.py; run via:
#   uv run --with plotly --with pandas python -c "import plotly_audit as pa; print(pa.audit(fig))"
def audit(fig_or_spec, df=None) -> list[Finding]:
    """Accepts a go.Figure / px figure OR a parsed to_dict() dict — covers live
    in-session audit AND pasted-JSON diagnosis. `df` optional, for axis-range-vs-data
    and log-axis-with-zero invariants. Kaleido never required by the audit itself."""
```

`Finding = {id, severity (error|warn|info), message, fix_hint, doc_ref}`. `doc_ref` is a `plotly.com/python/<slug>/` URL.

Checks (each grounded in the cited official doc):

| Check | doc_ref |
|---|---|
| empty trace / empty data | `/python/figure-structure/` |
| axis range vs data mismatch (needs `df`) | `/python/axes/` |
| legend off-canvas (`legend.x`>0.9, etc.) | `/python/legend/` |
| missing `hover_data` / `hovertemplate` | `/python/hover-text-and-formatting/` |
| missing color field / mapping | `/python/discrete-color/`, `/python/colorscales/` |
| `cliponaxis=True` with text labels → clipping | `/python/figure-introspection/` |
| duplicate trace names → legend binding | `/python/legend/` |
| margin too small for axis/title | `/python/setting-graph-size/`, `/python/axes/` |
| log axis with zero/negative data (`log(0)`) (needs `df`) | `/python/log-plot/` + `interactive-repl` `plot-iteration.md` |

## References (grounding)

- **`debugging-without-vision.md`** — the three-depth model + introspection toolset + escalation ladder + the `cliponaxis` case study. Grounded in `figure-introspection`, `figure-structure`, `static-image-export`, `renderers`.
- **`symptom-prescription.md`** — table: `user symptom | JSON checkpoint | fix code | official-doc URL`. Grounded in `legend`, `axes`, `hover-text-and-formatting`, `setting-graph-size`, `colorscales`, `discrete-color`, `tick-formatting`, `figure-labels`.
- **`px-patterns.md`** — one canonical `px` pattern per chart family (scatter, bar, line, histogram, box, violin, heatmap), each authored to match the official docs (`plotly-express` + the per-chart pages) and run through the audit. This is where "most example code, from the correct source" lives.
- **`notebook-delivery.md`** — `nbformat` assembly + execute-to-embed-outputs recipe.

## Relationship to other skills

- **`figure-style`:** the matplotlib / static-publication counterpart. Its render-then-verify-via-PNG-crops loop assumes the agent can `Read` PNGs; this skill is for when the figure is interactive Plotly (not auto-PNG'd by the `repl`) and the agent verifies structurally instead. Cross-link: each skill's "When NOT to use" points to the other.
- **`interactive-repl`:** the session/Jupyter engine. This skill is tool-agnostic — works with the `repl` MCP, the user's own Jupyter, or a script — but when the `repl` is available, the agent runs/audits figures in-session; the final notebook is executed via `nbconvert` to embed outputs. This skill bundles **no** MCP server.
- **`exploratory-data-analysis`:** data prep deferred there.
- **`figure-composer` / `paper-narrative`:** multi-panel publication arcs — out of scope.

## Testing

- **Size:** `./count-skill-tokens.py data-science/plotly-interactive-figures` — keep `SKILL.md` < 5000 tokens / 500 lines, `description` < 100 tokens.
- **Triggering:** copy to `~/.claude/skills/`, fresh session; should trigger on "make an interactive plotly chart," "plotly hover/zoom," "this plotly figure looks wrong," "debug this plotly"; should **not** trigger on matplotlib / publication figures (→`figure-style`) or "keep a session open" (→`interactive-repl`).
- **Audit pytest** (`tests/`, `locus-novelty`'s 33-test precedent): a synthetic fig per check, assert the expected `Finding`. Plus: `audit` accepts both a live fig and a parsed `to_dict()` dict; `audit` runs with **no Kaleido installed**.
- **End-to-end:** build a `px` scatter, audit it, assemble + execute a one-figure `.ipynb`, confirm the notebook opens with the embedded figure.

## License / attribution

- Our code (`plotly_audit.py`, `SKILL.md`, references): **MIT** (matches the repo).
- **Plotly.py** (`external/plotly.py`) is MIT-licensed; studied as read-only reference. Example code in `px-patterns.md` is authored here to be **faithful to** the official docs — not verbatim-copied — with the canonical `plotly.com/python/<slug>/` URL cited per pattern. The `external/` clone is a development-time reference only and is **not distributed** (gitignored per `CLAUDE.md`); the shipped skill cites public `plotly.com` URLs.
- `interactive-repl`'s `plot-iteration.md`: credited for the `log(0)` lesson and the `Read`-"Unsupported Image" → numerical-fallback pattern.

## Decisions made

- **Name:** `plotly-interactive-figures` (user's choice). The `description` frontmatter carries the no-visual-capability / debugging emphasis and "looks wrong" trigger.
- **Placement:** `data-science/` — interactive/exploratory, not publication-static (which would be `scientific-writing`).
- **Verification depth:** `to_dict`/`to_json` skeleton as the default channel (pure plotly, zero deps); Kaleido as **optional escalation** for `full_figure_for_development` (JS defaults) and `write_image`→`Read` (vision). Honest about the agent's actual capabilities; consistent with `figure-style`/`interactive-repl`, keeps the spec-primary thesis, puts vision as escalation — not default, not forbidden.
- **Audit form:** import-only module accepting a live fig **or** a parsed `to_dict()` dict — one function covers in-session audit and pasted-JSON diagnosis. `figure-style` pattern. No separate CLI (YAGNI); no `repl` sidecar (YAGNI, would tie it to Claude Code).
- **Deliverable:** `.ipynb` notebook (multiple figures + markdown commentary), assembled with `nbformat`, executed to embed outputs, written locally. The vision-less agent's primary way to hand the user a rich result.
- **Use case:** standard statistical `px` charts (quick exploration); `dash_bio` genomics interactive deferred — a separate, heavier dependency tier outside `px`.
- **Tool-agnostic:** no `mcpServers`; works with `repl` MCP / own Jupyter / script.
- **Source grounding:** example code + symptom prescriptions grounded in official Plotly.py docs (`external/` clone as dev reference; shipped skill cites `plotly.com` URLs).

## Provenance

Patterns adapted from: `figure-style` (import-only helper-module pattern, render-then-verify loop — reworked here as spec-verification), `interactive-repl`/`references/plot-iteration.md` (the "looking is necessary, not sufficient" / `log(0)` / `Read`-"Unsupported Image" lessons — here inverted to spec-first), and the official Plotly.py docs at `external/plotly.py/doc/python` (MIT) — the `figure-introspection` `cliponaxis` case study, the `to_dict`/`full_figure_for_development` model, and the per-chart `px` pages. Credited here for design traceability; the shipped `SKILL.md`, scripts, and references are original and self-contained, cite `plotly.com` public URLs, and do not reference openclaw-science or any external plugin.
