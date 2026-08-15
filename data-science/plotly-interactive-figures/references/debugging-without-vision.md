# Debugging Plotly figures without vision

A vision-less agent can't see a rendered figure — but a Plotly `Figure` is a
transparent JSON spec tree, so you can inspect and debug the *structure* without ever
rendering. Three depths, escalate only when the shallower one can't settle the problem.

## The three depths

### Depth 1 — Skeleton (default, pure plotly, zero deps)

`fig.to_dict()` / `fig.to_json()` returns only the attributes you set — the *skeleton*.
Plotly Express expands the dataframe into `data[].x`/`data[].y` arrays, so the skeleton
is self-contained: it carries the data. The audit (`scripts/plotly_audit.py`) operates
here. Also: `print(fig)` pretty-prints the spec; `fig.show("json")` gives an interactive
drilldown in JupyterLab. (Add the skill's `scripts/` to `sys.path` first — the exact
preamble is in SKILL.md's Audit step.)

```
import plotly_audit as pa
pa.audit(fig)            # live Figure
pa.audit(fig.to_dict())  # or a pasted spec
```

### Depth 2 — Full spec (Kaleido)

`fig.full_figure_for_development(warn=False)` returns the spec **after Plotly.js fills
in every default** — axis ranges, `cliponaxis`, tick layout, font sizes. This is the
root-cause finder: when the skeleton shows a manual setting but the *rendered* value
disagrees, the full spec reveals what Plotly.js actually used. Requires the
`kaleido` package (the same one used for static image export).

```
pip install kaleido            # or: uv run --with plotly --with kaleido python ...
full = fig.full_figure_for_development(warn=False)
print(full.layout.xaxis.range)      # the actual (JS-computed) range
print(full.data[0].cliponaxis)      # the actual cliponaxis
```

### Depth 3 — Vision (Kaleido, last resort)

For perceptual problems JSON can't decide (color harmony, true overlap, contrast),
render to PNG and `Read` it:

```
fig.write_image("fig.png")   # needs kaleido
# then: Read "fig.png"
```

If `Read` returns "Unsupported Image" (some environments can't render PNGs), fall back
to verifying key distribution stats numerically — `print(df[col].describe())` — and slow
down: when vision is unavailable, data-layer reasoning is *more* error-prone — even
with a render, a real session misread empty `scale_y_log10` panels as "censored
markers" when the true cause was `log(0)` undefined (looking is necessary, not
sufficient). See `interactive-repl`'s `references/plot-iteration.md`.

## The cliponaxis case study (canonical, from the official docs)

Text labels at the axis edge are clipped. The skeleton won't tell you clipping happens
(it's a render behavior), but the full spec reveals the cause:

```
import plotly.graph_objects as go
fig = go.Figure(go.Scatter(mode="markers+text", x=[10,20], y=[20,10], text=["A","B"]))
full = fig.full_figure_for_development(warn=False)
print(full.data[0].cliponaxis)   # True — the default that clips text at the axis
fig.update_traces(cliponaxis=False, textposition="top right")   # the fix
```

This is the symptom→JSON→fix loop, straight from the source. The audit's
`cliponaxis_text` check flags text traces with `cliponaxis` at its default `True` so
you catch this *before* the user sees clipping.

## Escalation ladder (read top-down, stop when settled)

1. `pa.audit(fig)` — structural defects from the skeleton (empty traces, off-canvas
   legend, `cliponaxis`-on-text, `log`-axis-with-≤0, manual range excluding data,
   duplicate names, disabled hover, short colorway, edge annotation with tiny margin).
2. Inspect the skeleton directly for anything the audit doesn't cover —
   `print(fig.to_json(pretty=True))` and read `data[]` / `layout`.
3. `full_figure_for_development()` — JS-computed defaults (Depth 2).
4. `write_image()`→`Read` — actually look (Depth 3), or numerical fallback.

## No silent caps

The audit checks what's structurally decidable from the skeleton. It does **not** check
color harmony, real overlap, contrast, or whether a title's rendered position collides
with a spine — those need Depth 2/3 or the user's eyes. When you deliver a figure,
say out loud which class of problem you did *not* verify (e.g. "color clash not
checkable without Kaleido — confirm visually or pull `write_image`→`Read`"). Never
imply a figure is verified when a whole category of defect went unchecked. The audit also
skips subplot axes (`x2`/`y2`) and container-relative legends (`xref='container'`) —
check those manually or escalate.

## Sources

- https://plotly.com/python/figure-introspection/ — the `cliponaxis` case, `full_figure_for_development`
- https://plotly.com/python/figure-structure/ — the `data`/`layout`/`frames` tree
- https://plotly.com/python/static-image-export/ — `write_image`, the Kaleido dependency
- https://plotly.com/python/renderers/ — `fig.show("json")`, renderer selection
