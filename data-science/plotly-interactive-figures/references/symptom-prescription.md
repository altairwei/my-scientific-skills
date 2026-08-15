# Symptom → JSON checkpoint → fix (diagnosis table)

When the user reports a visual symptom (they have eyes; you don't), map it to a JSON
checkpoint in the `to_dict()` spec and apply a surgical fix. Re-`audit` after.

| User symptom | JSON checkpoint | Fix | Source |
|---|---|---|---|
| "Right-side text/labels are cut off" | `layout.margin.r` small (or `annotations[].x ≥ 0.95` with small `margin.r`) | `fig.update_layout(margin=dict(r=80))` | https://plotly.com/python/setting-graph-size/ |
| "Legend covers the data" | `layout.legend.x` near `1.0` with `xanchor='left'` | `fig.update_layout(legend=dict(x=1.05, xanchor='left'))` | https://plotly.com/python/legend/ |
| "Text labels clipped at the axis edge" | trace `cliponaxis` default `True` (text mode) | `fig.update_traces(cliponaxis=False, selector=...)` | https://plotly.com/python/figure-introspection/ |
| "Hover doesn't show the name/column" | trace `hovertemplate`/`customdata` missing | `fig.update_traces(hovertemplate='%{x}: %{y}<br>%{customdata[0]}')` or `px.scatter(..., hover_data=['name'])` | https://plotly.com/python/hover-text-and-formatting/ |
| "Log axis dropped my zero/negative points" | `layout.yaxis.type == 'log'` with ≤0 in `trace.y` | use log only for strictly positive data; transform (`sqrt`) or filter | https://plotly.com/python/log-plot/ |
| "Bars/series colors repeat — can't tell apart" | `layout.colorway` shorter than `len(data)`, or no `color=` split | extend `colorway`, or remove it (default cycle), or `px.scatter(..., color='cat')` | https://plotly.com/python/discrete-color/ |
| "Axis tick labels overlap / unreadable" | no `tickangle`/`dtick` on a crowded axis | `fig.update_xaxes(tickangle=-45)` or `dtick=...` | https://plotly.com/python/tick-formatting/ |
| "Title or axis label is missing/too small" | `layout.title.text` / `layout.xaxis.title.text` absent | `fig.update_layout(title_text=..., xaxis_title_text=...)` | https://plotly.com/python/figure-labels/ |
| "Colors don't map to my category" | trace `marker.color` is a single color (no discrete split) | `px.scatter(df, ..., color='cat')` or `fig.update_traces(marker=dict(color=...))` | https://plotly.com/python/discrete-color/ |
| "Figure is cut off / wrong size when saved" | `layout.width`/`height`/`margin` unset | `fig.update_layout(width=900, height=500, margin=dict(t=60))` | https://plotly.com/python/setting-graph-size/ |
| "Color scale is wrong / not perceptually uniform" | `marker.colorscale` is qualitative on numeric, or reversed | set a sequential/diverging `colorscale` (e.g. `'Viridis'`), `reversescale=True` | https://plotly.com/python/colorscales/ |

## How to use it

1. Ask the user which symptom (or read their description; match the closest row).
2. Inspect the checkpoint: `print(fig.to_json(pretty=True))` or `fig.layout.legend.x`.
3. Apply the fix, then re-run `pa.audit(fig)` — confirm you didn't introduce a new
   structural defect.
4. If the symptom has no checkpoint here (a true perceptual call: "is this color
   clash acceptable?"), escalate per `debugging-without-vision.md` (Depth 3:
   `write_image`→`Read`) or hand it back to the user as a question.
