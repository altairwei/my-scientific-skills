# Canonical `px` patterns (grounded in the official docs, audited)

`px`-first; drop to `graph_objects` only when `px` can't express it. Each pattern below
matches the official Plotly docs and is run through `pa.audit`. Run them with:

```bash
uv run --with plotly --with pandas python your_script.py
```

```python
import pandas as pd
import plotly.express as px
import sys
sys.path.insert(0, "<plugin>/data-science/plotly-interactive-figures/scripts")
import plotly_audit as pa

# replace <plugin> with this repo's root, e.g. ~/src/my-scientific-skills

# small inline dataset — no network/data dep; 8 rows per category so
# box/violin quartiles are meaningful
df = pd.DataFrame({
    "category": [c for c in "abc" for _ in range(8)],
    "price":    [10, 12, 14, 16, 18, 20, 22, 24,
                 30, 33, 36, 39, 42, 45, 48, 51,
                 60, 63, 66, 69, 72, 75, 78, 81],
    "sales":    [5, 8, 6, 9, 4, 7, 5, 6, 4, 3, 5, 7, 6, 4, 5, 8, 3, 6, 4, 7, 5, 6, 4, 8],
    "region":   ["N", "S", "E", "W"] * 6,
})
```

## Scatter — https://plotly.com/python/line-and-scatter/

```python
fig = px.scatter(df, x="price", y="sales", color="category",
                 hover_data=["region"], title="price vs sales")
assert pa.audit(fig) == []
fig.show()
```

## Bar — https://plotly.com/python/bar-charts/

```python
agg = df.groupby("category", as_index=False)["sales"].sum()
fig = px.bar(agg, x="category", y="sales", color="category", title="sales by category")
assert pa.audit(fig) == []
fig.show()
```

## Line — https://plotly.com/python/line-charts/

```python
ts = pd.DataFrame({"t": range(6), "revenue": [1,3,2,5,4,6], "region": ["N","N","S","S","E","E"]})
fig = px.line(ts, x="t", y="revenue", color="region", title="revenue over time")
assert pa.audit(fig) == []
fig.show()
```

## Histogram — https://plotly.com/python/histograms/

```python
fig = px.histogram(df, x="price", color="category", barmode="overlay",
                   opacity=0.5, title="price distribution")
assert pa.audit(fig) == []
fig.show()
```

## Box — https://plotly.com/python/box-plots/

```python
fig = px.box(df, x="category", y="price", color="category", title="price by category")
assert pa.audit(fig) == []
fig.show()
```

## Violin — https://plotly.com/python/violin/

```python
fig = px.violin(df, x="category", y="price", color="category", box=True,
                title="price distribution (violin)")
assert pa.audit(fig) == []
fig.show()
```

## Heatmap (matrix) — https://plotly.com/python/heatmaps/

```python
import numpy as np
m = np.array([[1.0, 0.8, -0.4], [0.8, 1.0, 0.2], [-0.4, 0.2, 1.0]])  # a real correlation matrix
fig = px.imshow(m, title="correlation matrix",
                labels=dict(x="var", y="var", color="value"))
assert pa.audit(fig) == []
fig.show()
```

## When `px` isn't enough

`graph_objects` is the escape hatch (subplots, mixed trace types, `FigureWidget`, or
a categorical-x matrix `go.Heatmap` that `px.imshow` can't express). Audit still
applies — `pa.audit(fig)` works on any `go.Figure`. Prefer `px` until you hit a
concrete wall; document the wall in the notebook's markdown when you descend. If a
pattern's `assert pa.audit(fig) == []` ever trips, print the findings — each carries
a fix hint and a doc link (SKILL.md step 3).
