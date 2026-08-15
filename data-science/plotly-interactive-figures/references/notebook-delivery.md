# Delivering a `.ipynb` notebook

The skill's primary deliverable is a Jupyter notebook that organizes multiple figures
with markdown commentary — the vision-less agent's way to hand the user a rich result.
Assemble with `nbformat` (repeat the code-cell block once per figure, each preceded by
its own markdown note cell), execute to embed outputs, write locally with `Write`.

## Assemble + execute

```python
import nbformat as nbf
from nbformat.v4 import new_notebook, new_markdown_cell, new_code_cell

nb = new_notebook()
nb.cells = [
    new_markdown_cell("# Analysis\n\nAgent-authored summary: N rows, 3 categories, top outlier = …"),
    new_code_cell("""
import plotly.express as px
import sys; sys.path.insert(0, "<plugin>/data-science/plotly-interactive-figures/scripts")
# <plugin> = this repo's root, e.g. ~/src/my-scientific-skills
import plotly_audit as pa
df = px.data.tips()
fig = px.scatter(df, x="total_bill", y="tip", color="sex", hover_data=["day"])
print(pa.audit(fig))   # confirm structurally clean before delivery
fig.show()
"""),
    new_markdown_cell("## Note\n\nCategory C clusters top-right; may be dense — verify hover."),
]
nbf.write(nb, "analysis.ipynb")
```

Then execute headlessly to embed the rendered interactive figures as cell outputs:

```bash
uv run --with plotly --with pandas --with nbformat --with nbconvert --with ipykernel \
    jupyter nbconvert --to notebook --execute --inplace analysis.ipynb
```

Plotly figures embed as interactive HTML in the executed notebook — no display needed.
`nbconvert --execute` is the embedding path; the `interactive-repl` chunk tools are for
in-session iteration, not for embedding outputs into a `.ipynb`.

## Verify it embedded

You can't see the notebook — confirm structurally, like everything else in this skill.
Read the executed file back and assert the plotly mime type:

```python
import nbformat
nb = nbformat.read("analysis.ipynb", as_version=4)
code = [c for c in nb.cells if c.cell_type == "code"]
assert any("application/vnd.plotly.v1+json" in (o.get("data") or {})
           for c in code for o in c.get("outputs", []))
```

If a `fig.show()` silently produced a plain-text repr or an error, `nbconvert` still
exits 0 and writes the file — this assert is the only way to know the deliverable
isn't empty. (The plotly mime type is what JupyterLab's plotly extension renders; a
user reporting "raw JSON" means the extension is missing on their side, not a
notebook defect.)

## Deliver

Assemble and execute in a scratch directory, then `Read` the executed `analysis.ipynb`
and `Write` it into the project (the repo's no-upload convention — never
publish/upload a notebook containing research data). The user opens it in JupyterLab
and sees the live figures + your markdown commentary immediately.

## What goes in the markdown cells

- the agent's pre-computed data insights (rows, `nunique()`, top outliers) — your
  "eyes" as text;
- per-figure notes: what each figure shows, what to look at, known attention points;
- diagnostic reasoning: any symptom you diagnosed + the fix you applied;
- what you did NOT verify (per `debugging-without-vision.md`'s "no silent caps") —
  e.g. "color clash not checked without Kaleido."

## Sources

- https://plotly.com/python/renderers/ — `fig.show()` in a notebook embeds interactive HTML
- https://plotly.com/python/static-image-export/ — `write_image` if a static PNG cell output is wanted instead
