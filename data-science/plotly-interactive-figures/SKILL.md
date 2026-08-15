---
name: plotly-interactive-figures
description: Make, verify, and debug Plotly interactive figures when you (the agent)
  have no visual capability — diagnose plotting problems through the figure's JSON
  spec (to_dict/to_json, full_figure_for_development) instead of seeing the render.
  Deliver a Jupyter notebook (.ipynb) organizing multiple figures with markdown
  commentary. Use for interactive plotly/plotly-express charts, hover/zoom, or when a
  Plotly figure "looks wrong" and you can't see it. Route matplotlib/publication
  figures to figure-style.
license: MIT
metadata:
  author: Altair Wei
  version: "0.1"
---

# plotly-interactive-figures

Make, verify, and debug Plotly interactive figures **without seeing them**. A Plotly
`Figure` is a transparent JSON spec tree — `to_dict()`/`to_json()` exposes the
*skeleton* you set; `full_figure_for_development()` exposes the full spec after
Plotly.js fills defaults (axis ranges, `cliponaxis`, tick layout). You inspect and
debug that structure; rendering is the user's eyes, not yours. This is the vision-less
alternative to `figure-style`'s render-then-`Read`-PNG-crops loop (which assumes you can
see PNGs).

## The three depths (debug without vision)

| Depth | API | Use when | Dep |
|---|---|---|---|
| Skeleton | `fig.to_dict()` / `fig.to_json()` / `print(fig)` | always first — structural checks | plotly only |
| Full spec | `fig.full_figure_for_development(warn=False)` | the skeleton can't settle it (need JS-computed defaults) | Kaleido |
| Vision | `fig.write_image(p)` → `Read` p | residual perceptual cases (color, real overlap) | Kaleido; if `Read` says "Unsupported Image", verify numerically |

Default to the skeleton. Escalate to Kaleido only for the residual. Full model + the
`cliponaxis` case study: `references/debugging-without-vision.md`.

## Workflow

1. **Prep** (defer to `exploratory-data-analysis`) — load + clean. Before plotting,
   print a structured summary (rows, `nunique()`, top outliers) — your "eyes" as text,
   valuable even if a figure is later wrong.
2. **Build**, `px`-first (`px.scatter/bar/line/histogram/box/violin/heatmap`). Drop to
   `graph_objects` only when `px` can't express it. Patterns + the audit applied:
   `references/px-patterns.md`.
3. **Audit** (primary channel) —
   ```python
   import sys; sys.path.insert(0, "<plugin>/data-science/plotly-interactive-figures/scripts")
   import plotly_audit as pa
   for f in pa.audit(fig):
       print(f"[{f.severity}] {f.id}: {f.message}\n  fix: {f.fix_hint}\n  ref: {f.doc_ref}")
   ```
   Fix every `error`; triage `warn`s — `cliponaxis_text` is advisory ("labels may
   clip"), so only act when your labels actually approach an axis. `pa.audit` needs
   no Kaleido — it reads the `to_dict()` skeleton. `pa.audit(fig.to_dict())` also
   works on a pasted spec the user printed.
4. **Deliver a notebook** (`.ipynb`) — assemble multiple figures + markdown commentary
   with `nbformat`, execute with `jupyter nbconvert --execute --to notebook --inplace`
   (headless; Plotly embeds interactive HTML), `Write` it locally. Pattern:
   `references/notebook-delivery.md`. Never publish/upload.
5. **Diagnose** (user feedback) — when the user reports a symptom ("right text cut
   off", "legend covers data"), map it via `references/symptom-prescription.md` to a
   JSON checkpoint, apply the surgical `update_traces`/`update_layout` fix, re-audit.
6. **Escalate** (only the residual) — if the skeleton + symptom table can't settle a
   perceptual issue, pull Kaleido: `full_figure_for_development()` to see JS defaults,
   or `write_image()`→`Read` to actually look. Say out loud what you couldn't check
   without Kaleido — never imply a figure is verified when a class of problem went
   unchecked.

## When NOT to use

- **matplotlib / seaborn publication figures → `figure-style`** (its render-then-verify
  via PNG crops assumes you can `Read` PNGs; this skill is Plotly + spec-primary).
- **Multi-panel publication figure arc → `figure-composer` / `paper-narrative`.**
- **Persistent session / running cells → `interactive-repl`** (this skill is
  tool-agnostic: works with the `repl` MCP, your own Jupyter, or a script).
- **`dash_bio` interactive Manhattan/QQ → deferred** (heavier Dash-ecosystem dep, not `px`).

## Honest limits

JSON can't judge color harmony, true overlap perception, or contrast. Those go to the
Kaleido→`Read` escalation or the user-as-eyes loop. The audit flags what's
structurally checkable; the symptom table maps the rest. You don't "see" — you
confirm, structurally, that you haven't done it wrong.
