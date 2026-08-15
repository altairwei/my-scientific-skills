# plotly-interactive-figures Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a `plotly-interactive-figures` skill that lets a vision-less agent make, verify, and **debug** Plotly interactive figures through the figure's JSON spec, and deliver a multi-figure `.ipynb` notebook with markdown commentary.

**Architecture:** An import-only audit module (`scripts/plotly_audit.py`) — a pure-dict analyzer that accepts a live `go.Figure`/`px` figure OR a parsed `to_dict()` spec — plus four references (`debugging-without-vision.md`, `symptom-prescription.md`, `px-patterns.md`, `notebook-delivery.md`) grounded in the official Plotly.py docs. Tool-agnostic; no MCP server. Verification is spec-primary (`to_dict`/`to_json`) with Kaleido as optional escalation (`full_figure_for_development`, `write_image`→`Read`).

**Tech Stack:** Python ≥3.10, `plotly` (+ `pandas` for `px` input); `nbformat` + `nbconvert` for the notebook deliverable; `uv run --with` for zero-env bootstrapping; `pytest` for the audit suite.

**Spec:** `docs/superpowers/specs/2026-08-15-plotly-interactive-figures-design.md`

**Conventions used throughout:**
- Audit test command (union so any test runs): `uv run --with plotly --with pandas --with pytest python -m pytest data-science/plotly-interactive-figures/tests/ -v`
- The audit module is **pure-Python** — it operates on a `to_dict()` dict and imports **no** plotly at module level. `plotly` is needed only by whoever builds the figure (and by tests). `_to_spec()` duck-types: calls `.to_dict()` if present, else treats the input as an already-parsed spec dict. This means `pa.audit(fig.to_dict())` works on a user's pasted JSON with no plotly needed to inspect it.
- The `to_dict()` spec is **self-contained**: Plotly Express expands the dataframe into data arrays in `data[].x`/`data[].y`, so the audit reads data values straight from the spec — **no `df` parameter is needed** (the design spec's `df=None` is dropped; the spec carries the data).
- Official-doc grounding: while authoring example code, read `external/plotly.py/doc/python/<page>.md` (the gitignored clone). The **shipped** references cite public `https://plotly.com/python/<slug>/` URLs (the `external/` clone is never distributed).
- Commit after each task. If executing inline on `main`, first run `git checkout -b feat/plotly-interactive-figures` — unless working on `main` with explicit user consent (per executing-plans skill).

## File Structure

- **Create** `data-science/plotly-interactive-figures/SKILL.md` — the protocol (prep→build→audit→deliver→diagnose; Kaleido escalation)
- **Create** `data-science/plotly-interactive-figures/scripts/plotly_audit.py` — import-only: `audit(fig_or_spec) -> list[Finding]`, 9 structural checks
- **Create** `data-science/plotly-interactive-figures/references/debugging-without-vision.md` — three-depth methodology + cliponaxis case + escalation ladder
- **Create** `data-science/plotly-interactive-figures/references/symptom-prescription.md` — symptom → JSON checkpoint → fix → official-doc URL table
- **Create** `data-science/plotly-interactive-figures/references/px-patterns.md` — one canonical `px` pattern per chart family, grounded in docs, audited
- **Create** `data-science/plotly-interactive-figures/references/notebook-delivery.md` — `nbformat` assembly + `nbconvert --execute`
- **Create** `data-science/plotly-interactive-figures/tests/conftest.py` — puts `scripts/` on `sys.path`
- **Create** `data-science/plotly-interactive-figures/tests/test_audit.py` — one test per check + entrypoint tests
- **Modify** `.claude-plugin/marketplace.json` — add `./data-science/plotly-interactive-figures` to the `data-science` plugin's `skills`
- **Modify** `README.md` — add the skill row to the data-science table

---

### Task 1: Scaffold + marketplace + README + conftest + audit skeleton

**Files:**
- Create: `data-science/plotly-interactive-figures/scripts/plotly_audit.py` (skeleton: `Finding` + `_to_spec` + `audit()` returning `[]`)
- Create: `data-science/plotly-interactive-figures/tests/conftest.py`
- Create: `data-science/plotly-interactive-figures/tests/test_audit.py` (entrypoint tests only)
- Modify: `.claude-plugin/marketplace.json`
- Modify: `README.md`

- [ ] **Step 1: Create the directory tree**

Run:
```bash
mkdir -p data-science/plotly-interactive-figures/scripts \
         data-science/plotly-interactive-figures/references \
         data-science/plotly-interactive-figures/tests
```

- [ ] **Step 2: Write `tests/conftest.py`**

```python
# data-science/plotly-interactive-figures/tests/conftest.py
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
```

- [ ] **Step 3: Write the failing entrypoint tests**

```python
# data-science/plotly-interactive-figures/tests/test_audit.py
"""Tests for plotly_audit.py (import-only Plotly figure auditor).

Run via uv (no display, no Kaleido needed):

  uv run --with plotly --with pandas --with pytest \
      python -m pytest data-science/plotly-interactive-figures/tests/ -v
"""
import plotly.graph_objects as go
import pytest

import plotly_audit as pa  # via conftest sys.path


def _ids(findings):
    return [f.id for f in findings]


# ── audit() entrypoint ────────────────────────────────────────────────────────

def test_audit_accepts_dict_spec_and_returns_list():
    spec = {"data": [{"type": "scatter", "x": [1, 2], "y": [3, 4]}], "layout": {}}
    out = pa.audit(spec)
    assert isinstance(out, list)


def test_audit_accepts_go_figure():
    fig = go.Figure(go.Scatter(x=[1, 2], y=[3, 4]))
    out = pa.audit(fig)
    assert isinstance(out, list)


def test_audit_rejects_garbage():
    with pytest.raises(TypeError, match="to_dict"):
        pa.audit(42)


def test_audit_rejects_dataframe():
    import pandas as pd
    df = pd.DataFrame({"x": [1, 2], "y": [3, 4]})
    with pytest.raises(TypeError, match="to_dict"):
        pa.audit(df)


def test_finding_as_dict_roundtrip():
    f = pa.Finding("x", "warn", "msg", "fix", "https://plotly.com/python/legend/")
    assert f.as_dict() == {"id": "x", "severity": "warn", "message": "msg",
                           "fix_hint": "fix", "doc_ref": "https://plotly.com/python/legend/"}


def test_clean_scatter_has_no_errors():
    fig = go.Figure(go.Scatter(x=[1, 2, 3], y=[1, 2, 3], name="s1"))
    errs = [f for f in pa.audit(fig) if f.severity == "error"]
    assert errs == []
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `uv run --with plotly --with pandas --with pytest python -m pytest data-science/plotly-interactive-figures/tests/ -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'plotly_audit'`.

- [ ] **Step 5: Write the `plotly_audit.py` skeleton**

```python
# data-science/plotly-interactive-figures/scripts/plotly_audit.py
"""plotly_audit — structural verification of Plotly figures for vision-less agents.

Import-only module (no CLI), mirroring figure_style. The agent inspects a figure's
to_dict() spec to catch structural defects before render, and to diagnose
user-reported symptoms. Operates on a plain dict (the to_dict() output), so this
module imports NO plotly — plotly is needed only by whoever builds the figure.

Usage:

    import sys
    sys.path.insert(0, "<plugin>/data-science/plotly-interactive-figures/scripts")
    import plotly_audit as pa
    for f in pa.audit(fig):              # live go.Figure / px figure
        print(f"[{f.severity}] {f.id}: {f.message}\\n  fix: {f.fix_hint}\\n  ref: {f.doc_ref}")
    # or audit a pasted spec the user printed:
    pa.audit(fig.to_dict())

Run tests:

    uv run --with plotly --with pandas --with pytest \\
        python -m pytest data-science/plotly-interactive-figures/tests/ -v

`doc_ref` values point at https://plotly.com/python/<slug>/. See the skill's
references/debugging-without-vision.md for the three-depth model this audit is the
first depth of.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DOC = "https://plotly.com/python/"


@dataclass(frozen=True)
class Finding:
    id: str
    severity: str            # "error" | "warn" | "info"
    message: str
    fix_hint: str = ""
    doc_ref: str = ""

    def as_dict(self) -> dict:
        return {"id": self.id, "severity": self.severity, "message": self.message,
                "fix_hint": self.fix_hint, "doc_ref": self.doc_ref}


def _to_spec(fig_or_spec: Any) -> dict:
    """Accept a go.Figure / px figure (duck-typed .to_dict) or a parsed spec dict.

    Dict-first: pandas DataFrames also have a .to_dict() whose output has no
    "data" key — reject them (shape-check) instead of silently auditing {}.
    """
    if isinstance(fig_or_spec, dict):
        return fig_or_spec
    if hasattr(fig_or_spec, "to_dict"):
        spec = fig_or_spec.to_dict()
        if isinstance(spec, dict) and "data" in spec:
            return spec
    raise TypeError(
        f"audit() expects a Plotly Figure or a to_dict() dict, got {type(fig_or_spec).__name__}")


def audit(fig_or_spec: Any) -> list[Finding]:
    """Run all structural checks on a figure's to_dict() spec.

    Pure: no rendering, no Kaleido. Default-depth (skeleton) verification — the
    first of the three depths in references/debugging-without-vision.md.
    """
    spec = _to_spec(fig_or_spec)
    findings: list[Finding] = []
    for check in _CHECKS:
        findings.extend(check(spec))
    return findings


# ── check helpers ──────────────────────────────────────────────────────────────

def _traces(spec: dict) -> list[dict]:
    return spec.get("data", []) or []


def _layout(spec: dict) -> dict:
    return spec.get("layout", {}) or {}


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


# Checks are appended in later tasks; start empty so audit() is a no-op here.
_CHECKS: list = []
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --with plotly --with pandas --with pytest python -m pytest data-science/plotly-interactive-figures/tests/ -v`
Expected: 6 passed. (`audit()` returns `[]` because `_CHECKS` is empty; the clean-scatter test therefore has no errors.)

- [ ] **Step 7: Add `plotly-interactive-figures` to `marketplace.json`**

In `.claude-plugin/marketplace.json`, add `"./data-science/plotly-interactive-figures"` to the `data-science` plugin's `skills` list (after `"./data-science/interactive-repl"`). **No `mcpServers` change** — this is a pure-script skill (the existing `repl` mcpServers stay as-is).

- [ ] **Step 8: Add the skill row to `README.md`**

In the data-science skills table in `README.md`, add this row after the `interactive-repl` row:
```
| [plotly-interactive-figures](data-science/plotly-interactive-figures/) | Make, verify, and debug Plotly interactive figures without visual capability — diagnose plotting problems through the figure's JSON spec (`to_dict`/`to_json`, `full_figure_for_development`) instead of seeing the render; delivers a multi-figure `.ipynb` notebook with markdown commentary; `px`-first, Kaleido as optional escalation |
```

- [ ] **Step 9: Verify JSON parses**

Run: `python -c "import json; d=json.load(open('.claude-plugin/marketplace.json')); print('json ok'); print([s for p in d['plugins'] if p['name']=='data-science' for s in p['skills']])"`
Expected: `json ok` and the skills list includes `./data-science/plotly-interactive-figures`.

- [ ] **Step 10: Commit**

```bash
git add data-science/plotly-interactive-figures/ .claude-plugin/marketplace.json README.md
git commit -m "feat(plotly-interactive-figures): scaffold + audit skeleton + marketplace registration"
```

---

### Task 2: `empty_trace` + `duplicate_trace_name` checks

**Files:**
- Modify: `data-science/plotly-interactive-figures/scripts/plotly_audit.py` (add 2 checks, register in `_CHECKS`)
- Modify: `data-science/plotly-interactive-figures/tests/test_audit.py` (add 4 tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_audit.py`:

```python
# ── empty traces ───────────────────────────────────────────────────────────────

def test_empty_trace_flagged():
    fig = go.Figure(go.Scatter(x=[], y=[]))
    assert "empty_trace" in _ids(pa.audit(fig))


def test_empty_trace_has_doc_ref():
    fig = go.Figure(go.Scatter(x=[], y=[]))
    f = [x for x in pa.audit(fig) if x.id == "empty_trace"][0]
    assert f.severity == "error"
    assert f.doc_ref == "https://plotly.com/python/figure-structure/"


# ── duplicate trace names ──────────────────────────────────────────────────────

def test_duplicate_names_flagged():
    fig = go.Figure([go.Scatter(x=[1], y=[1], name="dup"),
                     go.Scatter(x=[1], y=[2], name="dup")])
    assert "duplicate_trace_name" in _ids(pa.audit(fig))


def test_unique_names_not_flagged():
    fig = go.Figure([go.Scatter(x=[1], y=[1], name="a"),
                     go.Scatter(x=[1], y=[2], name="b")])
    assert "duplicate_trace_name" not in _ids(pa.audit(fig))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with plotly --with pandas --with pytest python -m pytest data-science/plotly-interactive-figures/tests/ -v`
Expected: FAIL — `assert "empty_trace" in _ids(...)` fails (audit still returns `[]`).

- [ ] **Step 3: Implement the two checks**

In `scripts/plotly_audit.py`, add these functions after the `_is_num` helper:

```python
def _check_empty_traces(spec: dict) -> list[Finding]:
    out = []
    for i, tr in enumerate(_traces(spec)):
        for axis in ("x", "y", "z", "values", "labels"):
            v = tr.get(axis)
            if v is None:
                continue
            if hasattr(v, "__len__") and len(v) == 0:
                out.append(Finding("empty_trace", "error",
                    f"trace[{i}] ({tr.get('type', 'scatter')}) has empty '{axis}'",
                    f"fig.data[{i}].{axis} is empty — drop the trace or supply data",
                    DOC + "figure-structure/"))
                break
    return out


def _check_duplicate_names(spec: dict) -> list[Finding]:
    out = []
    seen: dict = {}
    for i, tr in enumerate(_traces(spec)):
        n = tr.get("name")
        if not n:
            continue
        if n in seen:
            out.append(Finding("duplicate_trace_name", "warn",
                f"trace[{i}] reuses name {n!r} (also trace[{seen[n]}]) — legend/hover binding is ambiguous",
                "give each trace a unique name, or use legendgroup",
                DOC + "legend/"))
        else:
            seen[n] = i
    return out
```

Then register them — replace the `_CHECKS` line:
```python
_CHECKS: list = []
```
with:
```python
_CHECKS = [_check_empty_traces, _check_duplicate_names]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with plotly --with pandas --with pytest python -m pytest data-science/plotly-interactive-figures/tests/ -v`
Expected: all tests PASS (6 entrypoint + 4 new = 10).

- [ ] **Step 5: Commit**

```bash
git add data-science/plotly-interactive-figures/scripts/plotly_audit.py data-science/plotly-interactive-figures/tests/test_audit.py
git commit -m "feat(plotly-interactive-figures): empty-trace + duplicate-name checks"
```

---

### Task 3: `cliponaxis_text` + `hover_disabled` checks

**Files:**
- Modify: `data-science/plotly-interactive-figures/scripts/plotly_audit.py`
- Modify: `data-science/plotly-interactive-figures/tests/test_audit.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_audit.py`:

```python
# ── cliponaxis + text ──────────────────────────────────────────────────────────

def test_text_trace_cliponaxis_flagged():
    fig = go.Figure(go.Scatter(x=[1, 2], y=[1, 2], text=["a", "b"], mode="markers+text"))
    assert "cliponaxis_text" in _ids(pa.audit(fig))


def test_cliponaxis_false_not_flagged():
    fig = go.Figure(go.Scatter(x=[1, 2], y=[1, 2], text=["a", "b"],
                               mode="markers+text", cliponaxis=False))
    assert "cliponaxis_text" not in _ids(pa.audit(fig))


# ── hover disabled ─────────────────────────────────────────────────────────────

def test_hoverinfo_none_flagged():
    fig = go.Figure(go.Scatter(x=[1], y=[1], hoverinfo="none"))
    assert "hover_disabled" in _ids(pa.audit(fig))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with plotly --with pandas --with pytest python -m pytest data-science/plotly-interactive-figures/tests/ -v`
Expected: FAIL — `cliponaxis_text` / `hover_disabled` not produced.

- [ ] **Step 3: Implement the two checks**

Add to `scripts/plotly_audit.py`:

```python
def _check_cliponaxis_text(spec: dict) -> list[Finding]:
    # cliponaxis defaults to True (per the official figure-introspection doc); text
    # labels crossing an axis line are clipped when it's True. Only the scatter
    # family has a cliponaxis property — Scattergl/Scatter3d/Scattergeo/Scattermap
    # reject it (update_traces(cliponaxis=...) raises ValueError there).
    out = []
    for i, tr in enumerate(_traces(spec)):
        mode = tr.get("mode") or ""
        if "text" not in mode:
            continue
        ttype = tr.get("type", "scatter")
        if "cliponaxis" not in tr and ttype not in ("scatter", "scatterpolar", "scatterternary"):
            continue
        clip = tr.get("cliponaxis")
        if clip is None or clip is True:
            shown = "default True" if clip is None else "True"
            out.append(Finding("cliponaxis_text", "warn",
                f"trace[{i}] shows text with cliponaxis={shown} — labels crossing an axis line will be clipped at the edge",
                "fig.update_traces(cliponaxis=False, selector=...) keeps text visible past the axes",
                DOC + "figure-introspection/"))
    return out


def _check_hover_disabled(spec: dict) -> list[Finding]:
    out = []
    for i, tr in enumerate(_traces(spec)):
        if tr.get("hoverinfo") == "none":
            out.append(Finding("hover_disabled", "warn",
                f"trace[{i}] has hoverinfo='none' — hover is fully disabled on this trace",
                "remove hoverinfo='none', or set a hovertemplate for richer hover",
                DOC + "hover-text-and-formatting/"))
    return out
```

Register them — change:
```python
_CHECKS = [_check_empty_traces, _check_duplicate_names]
```
to:
```python
_CHECKS = [_check_empty_traces, _check_duplicate_names,
           _check_cliponaxis_text, _check_hover_disabled]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with plotly --with pandas --with pytest python -m pytest data-science/plotly-interactive-figures/tests/ -v`
Expected: all PASS (16 total: 13 + 3 regression tests from the post-review trace-type gate).

- [ ] **Step 5: Commit**

```bash
git add data-science/plotly-interactive-figures/scripts/plotly_audit.py data-science/plotly-interactive-figures/tests/test_audit.py
git commit -m "feat(plotly-interactive-figures): cliponaxis-text + hover-disabled checks"
```

---

### Task 4: `legend_off_canvas` + `colorway_shorter_than_traces` checks

**Files:**
- Modify: `data-science/plotly-interactive-figures/scripts/plotly_audit.py`
- Modify: `data-science/plotly-interactive-figures/tests/test_audit.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_audit.py`:

```python
# ── legend off canvas ──────────────────────────────────────────────────────────

def test_legend_off_right_edge_flagged():
    fig = go.Figure(go.Scatter(x=[1, 2], y=[1, 2]))
    fig.update_layout(legend=dict(x=0.95, xanchor="left"))
    assert "legend_off_canvas" in _ids(pa.audit(fig))


def test_legend_pushed_into_margin_ok():
    fig = go.Figure(go.Scatter(x=[1, 2], y=[1, 2]))
    fig.update_layout(legend=dict(x=1.05, xanchor="left"))
    assert "legend_off_canvas" not in _ids(pa.audit(fig))


# ── colorway shorter than traces ───────────────────────────────────────────────

def test_colorway_shorter_than_traces_flagged():
    fig = go.Figure([go.Scatter(x=[1], y=[1], name="a"),
                     go.Scatter(x=[1], y=[2], name="b"),
                     go.Scatter(x=[1], y=[3], name="c")])
    fig.update_layout(colorway=["red", "blue"])   # 2 colors, 3 traces
    assert "colorway_shorter_than_traces" in _ids(pa.audit(fig))


def test_no_colorway_not_flagged():
    fig = go.Figure([go.Scatter(x=[1], y=[1], name="a"),
                     go.Scatter(x=[1], y=[2], name="b")])
    assert "colorway_shorter_than_traces" not in _ids(pa.audit(fig))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with plotly --with pandas --with pytest python -m pytest data-science/plotly-interactive-figures/tests/ -v`
Expected: FAIL.

- [ ] **Step 3: Implement the two checks**

Add to `scripts/plotly_audit.py`:

```python
def _check_legend_off_canvas(spec: dict) -> list[Finding]:
    out = []
    leg = _layout(spec).get("legend")
    if not isinstance(leg, dict):
        return out
    x = leg.get("x")
    xa = leg.get("xanchor", "left")
    if _is_num(x):
        # Only the straddling zone flags: with xanchor="left" the legend extends
        # rightward from x, so 0.9 < x < 1.0 means it hangs over the plot's right
        # edge. x >= 1.0 (e.g. Plotly's default 1.02) sits wholly in the margin.
        if 0.9 < x < 1.0 and xa in ("left", "auto"):
            out.append(Finding("legend_off_canvas", "warn",
                f"legend.x={x} with xanchor={xa!r} sits at/over the right edge — may be clipped",
                "fig.update_layout(legend=dict(x=1.05, xanchor='left')) to push it into the right margin",
                DOC + "legend/"))
        elif 0 < x < 0.05 and xa in ("right", "auto"):
            out.append(Finding("legend_off_canvas", "warn",
                f"legend.x={x} with xanchor={xa!r} sits at/over the left edge — may be clipped",
                "fig.update_layout(legend=dict(x=-0.05, xanchor='right'))",
                DOC + "legend/"))
    return out


def _check_colorway_short(spec: dict) -> list[Finding]:
    out = []
    cw = _layout(spec).get("colorway")
    if not isinstance(cw, list) or not cw:
        return out
    n = len(_traces(spec))
    if n > len(cw):
        out.append(Finding("colorway_shorter_than_traces", "warn",
            f"layout.colorway has {len(cw)} colors for {n} traces — colors repeat; series may be hard to tell apart",
            "extend colorway, or remove it to use Plotly's default cycle",
            DOC + "discrete-color/"))
    return out
```

Register them — change:
```python
_CHECKS = [_check_empty_traces, _check_duplicate_names,
           _check_cliponaxis_text, _check_hover_disabled]
```
to:
```python
_CHECKS = [_check_empty_traces, _check_duplicate_names,
           _check_cliponaxis_text, _check_hover_disabled,
           _check_legend_off_canvas, _check_colorway_short]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with plotly --with pandas --with pytest python -m pytest data-science/plotly-interactive-figures/tests/ -v`
Expected: all PASS (20 total).

- [ ] **Step 5: Commit**

```bash
git add data-science/plotly-interactive-figures/scripts/plotly_audit.py data-science/plotly-interactive-figures/tests/test_audit.py
git commit -m "feat(plotly-interactive-figures): legend-off-canvas + colorway-short checks"
```

---

### Task 5: `log_axis_nonpositive` + `axis_range_excludes_data` checks

**Files:**
- Modify: `data-science/plotly-interactive-figures/scripts/plotly_audit.py`
- Modify: `data-science/plotly-interactive-figures/tests/test_audit.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_audit.py`:

```python
# ── log axis nonpositive ───────────────────────────────────────────────────────

def test_log_axis_with_zero_flagged():
    fig = go.Figure(go.Scatter(x=[1, 2, 3], y=[1, 0, 4]))
    fig.update_yaxes(type="log")
    assert "log_axis_nonpositive" in _ids(pa.audit(fig))


def test_log_axis_all_positive_not_flagged():
    fig = go.Figure(go.Scatter(x=[1, 2, 3], y=[1, 10, 100]))
    fig.update_yaxes(type="log")
    assert "log_axis_nonpositive" not in _ids(pa.audit(fig))


# ── axis range excludes data ───────────────────────────────────────────────────

def test_manual_range_excluding_data_flagged():
    fig = go.Figure(go.Scatter(x=[1, 2, 3, 4], y=[1, 2, 3, 4]))
    fig.update_xaxes(range=[0, 3])   # x=4 is outside
    assert "axis_range_excludes_data" in _ids(pa.audit(fig))


def test_autorange_not_flagged():
    fig = go.Figure(go.Scatter(x=[1, 2, 3, 4], y=[1, 2, 3, 4]))
    assert "axis_range_excludes_data" not in _ids(pa.audit(fig))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with plotly --with pandas --with pytest python -m pytest data-science/plotly-interactive-figures/tests/ -v`
Expected: FAIL.

- [ ] **Step 3: Implement the two checks**

Add to `scripts/plotly_audit.py`:

```python
# (add `import array` and `import base64` to the module's top import block)
_DTYPE_SPEC = {
    "i1": "b", "u1": "B", "i2": "h", "u2": "H",
    "i4": "i", "u4": "I", "i8": "q", "u8": "Q",
    "f4": "f", "f8": "d",
}


def _decode_values(v: Any) -> Any:
    """Normalize a to_dict() value. Plain list/tuple passes through; plotly 6.x
    serializes numpy-backed arrays as typed-array dicts {"dtype","bdata"} —
    decode them stdlib-only (base64 + array), preserving the no-plotly import."""
    if isinstance(v, (list, tuple)):
        return list(v)
    if isinstance(v, dict) and "bdata" in v and "dtype" in v:
        raw = base64.b64decode(v["bdata"])
        code = _DTYPE_SPEC.get(v["dtype"])
        if code is not None:
            try:
                return list(array.array(code, raw))
            except (ValueError, OverflowError):
                pass
        try:
            return list(array.array("d", raw))
        except (ValueError, OverflowError):
            return list(raw)
    return v


def _axis_vals(spec: dict, trace_key: str, axis_ref: str) -> list:
    """Numeric values on `trace_key` from traces bound to axis `axis_ref`
    ("x"/"y"). x2/y2-bound traces are excluded (subplot axes are a v1
    limitation — see the plan)."""
    vals = []
    for tr in _traces(spec):
        if tr.get(f"{axis_ref}axis", axis_ref) != axis_ref:
            continue
        data = _decode_values(tr.get(trace_key))
        if isinstance(data, (list, tuple)):
            vals.extend(v for v in data if _is_num(v))
    return vals


def _check_log_axis_nonpositive(spec: dict) -> list[Finding]:
    out = []
    layout = _layout(spec)
    for axis_key, trace_key, axis_ref in (("xaxis", "x", "x"), ("yaxis", "y", "y")):
        ax = layout.get(axis_key)
        if not isinstance(ax, dict) or ax.get("type") != "log":
            continue
        vals = _axis_vals(spec, trace_key, axis_ref)
        nonpos = [v for v in vals if v <= 0]
        if nonpos:
            out.append(Finding("log_axis_nonpositive", "error",
                f"{axis_key} is log-scaled but {len(nonpos)} of {len(vals)} data points are ≤ 0 — log(0) is undefined; these points vanish",
                "use a log axis only for strictly positive data, or transform (e.g. sqrt), or filter ≤0 first",
                DOC + "log-plot/"))
    return out


def _check_axis_range_excludes_data(spec: dict) -> list[Finding]:
    out = []
    layout = _layout(spec)
    for axis_key, trace_key, axis_ref in (("xaxis", "x", "x"), ("yaxis", "y", "y")):
        ax = layout.get(axis_key)
        if not isinstance(ax, dict):
            continue
        rng = ax.get("range")
        if not (isinstance(rng, list) and len(rng) == 2 and all(_is_num(v) for v in rng)):
            continue
        lo, hi = rng
        if lo > hi:
            lo, hi = hi, lo              # autorange-reversed
        vals = _axis_vals(spec, trace_key, axis_ref)
        if not vals:
            continue
        outside = [v for v in vals if v < lo or v > hi]
        if outside:
            out.append(Finding("axis_range_excludes_data", "warn",
                f"{axis_key}.range=[{rng[0]},{rng[1]}] excludes {len(outside)}/{len(vals)} data points — they will not render",
                "widen the range, or set range=None (autorange) so Plotly.js computes it from the data",
                DOC + "axes/"))
    return out
```

Register them — change:
```python
_CHECKS = [_check_empty_traces, _check_duplicate_names,
           _check_cliponaxis_text, _check_hover_disabled,
           _check_legend_off_canvas, _check_colorway_short]
```
to:
```python
_CHECKS = [_check_empty_traces, _check_duplicate_names,
           _check_cliponaxis_text, _check_hover_disabled,
           _check_legend_off_canvas, _check_colorway_short,
           _check_log_axis_nonpositive, _check_axis_range_excludes_data]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with plotly --with pandas --with pytest python -m pytest data-science/plotly-interactive-figures/tests/ -v`
Expected: all PASS (29 total: 24 + 5 regression tests from the post-review typed-array fix).

- [ ] **Step 5: Commit**

```bash
git add data-science/plotly-interactive-figures/scripts/plotly_audit.py data-science/plotly-interactive-figures/tests/test_audit.py
git commit -m "feat(plotly-interactive-figures): log-axis-nonpositive + axis-range-excludes-data checks"
```

---

### Task 6: `margin_vs_edge_content` check

**Files:**
- Modify: `data-science/plotly-interactive-figures/scripts/plotly_audit.py`
- Modify: `data-science/plotly-interactive-figures/tests/test_audit.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_audit.py`:

```python
# ── margin vs edge annotation ─────────────────────────────────────────────────

def test_small_right_margin_with_edge_annotation_flagged():
    fig = go.Figure(go.Scatter(x=[1, 2], y=[1, 2]))
    fig.update_layout(margin=dict(r=10),
                      annotations=[dict(text="note", x=0.98, y=0.5, xref="paper", yref="paper")])
    assert any(i.startswith("margin_") for i in _ids(pa.audit(fig)))


def test_default_margin_not_flagged():
    fig = go.Figure(go.Scatter(x=[1, 2], y=[1, 2]))
    assert not any(i.startswith("margin_") for i in _ids(pa.audit(fig)))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --with plotly --with pandas --with pytest python -m pytest data-science/plotly-interactive-figures/tests/ -v`
Expected: FAIL.

- [ ] **Step 3: Implement the check**

Add to `scripts/plotly_audit.py`:

```python
def _check_margin_vs_edge_content(spec: dict) -> list[Finding]:
    # A small margin on a side that has paper-coord content (annotation near the
    # edge) risks clipping. Axis-title clipping can't be checked from the skeleton
    # (its rendered position is a Plotly.js default) — that goes to the
    # full_figure_for_development escalation, not this check.
    out = []
    layout = _layout(spec)
    margin = layout.get("margin", {}) or {}
    anns = layout.get("annotations", []) or []
    edges = [("right", "r", 0.95, 1.0, "x", "xref"), ("left", "l", 0.0, 0.05, "x", "xref"),
             ("top", "t", 0.95, 1.0, "y", "yref"), ("bottom", "b", 0.0, 0.05, "y", "yref")]
    for side, mkey, lo, hi, anchor_axis, ref_key in edges:
        m = margin.get(mkey)
        if m is None or m >= 20:
            continue
        # paper-reference only: annotations default to DATA coords (plain
        # add_annotation leaves xref absent; full_figure_for_development shows the
        # effective default is "x") — only an explicitly-paper annotation is
        # edge-judgeable from the skeleton.
        near = [a for a in anns
                if _is_num(a.get(anchor_axis)) and lo <= a[anchor_axis] <= hi
                and a.get(ref_key) == "paper"]
        if near:
            out.append(Finding(f"margin_{side}_edge", "info",
                f"margin.{mkey}={m} but {len(near)} annotation(s) sit at the {side} edge (paper {lo}-{hi}) — may be clipped",
                f"fig.update_layout(margin=dict({mkey}=40)) to reserve space for edge content",
                DOC + "setting-graph-size/"))
    return out
```

Register it — change:
```python
           _check_log_axis_nonpositive, _check_axis_range_excludes_data]
```
to:
```python
           _check_log_axis_nonpositive, _check_axis_range_excludes_data,
           _check_margin_vs_edge_content]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run --with plotly --with pandas --with pytest python -m pytest data-science/plotly-interactive-figures/tests/ -v`
Expected: all PASS (35 total: 31 + 4 regression tests from the post-review xref filter).

- [ ] **Step 5: Verify a clean `px` figure audits clean (real-API smoke)**

Run:
```bash
uv run --with plotly --with pandas python -c "
import sys; sys.path.insert(0,'data-science/plotly-interactive-figures/scripts')
import plotly_audit as pa, plotly.express as px
df = px.data.tips()
fig = px.scatter(df, x='total_bill', y='tip', color='sex', hover_data=['day'])
print(pa.audit(fig))
"
```
Expected: prints `[]` (or only `info`-level findings) — a clean px figure produces no errors/warns. If a check has a false positive on a real px figure, fix the check.

- [ ] **Step 6: Commit**

```bash
git add data-science/plotly-interactive-figures/scripts/plotly_audit.py data-science/plotly-interactive-figures/tests/test_audit.py
git commit -m "feat(plotly-interactive-figures): margin-vs-edge-content check + px clean smoke"
```

---

### Task 7: `SKILL.md` — the protocol

**Files:**
- Create: `data-science/plotly-interactive-figures/SKILL.md`

- [ ] **Step 1: Write `SKILL.md`**

```markdown
---
name: plotly-interactive-figures
description: Make, verify, and debug Plotly interactive figures when you (the agent)
  have no visual capability — diagnose problems through the figure's JSON spec
  (to_dict/to_json, full_figure_for_development) instead of seeing the render. Deliver
  a .ipynb notebook of figures + markdown commentary. Triggers on interactive
  plotly/plotly-express charts, hover/zoom, or "this plotly looks wrong". Route
  matplotlib/publication figures to figure-style.
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
   # <plugin> = this repo's root, e.g. ~/src/my-scientific-skills
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
```

- [ ] **Step 2: Size check**

Run: `./count-skill-tokens.py data-science/plotly-interactive-figures`
Expected: `SKILL.md` under 500 lines / ~5k tokens; `description` under ~100 tokens. Trim if it warns.

- [ ] **Step 3: Commit**

```bash
git add data-science/plotly-interactive-figures/SKILL.md
git commit -m "feat(plotly-interactive-figures): SKILL.md protocol + three-depth workflow"
```

---

### Task 8: `references/debugging-without-vision.md`

**Files:**
- Create: `data-science/plotly-interactive-figures/references/debugging-without-vision.md`

Grounded in the official docs `figure-introspection.md`, `figure-structure.md`, `static-image-export.md`, `renderers.md` (read from `external/plotly.py/doc/python/` while authoring).

- [ ] **Step 1: Write the reference**

```markdown
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
imply a figure is verified when a whole category of defect went unchecked.

## Sources

- https://plotly.com/python/figure-introspection/ — the `cliponaxis` case, `full_figure_for_development`
- https://plotly.com/python/figure-structure/ — the `data`/`layout`/`frames` tree
- https://plotly.com/python/static-image-export/ — `write_image`, the Kaleido dependency
- https://plotly.com/python/renderers/ — `fig.show("json")`, renderer selection
```

- [ ] **Step 2: Commit**

```bash
git add data-science/plotly-interactive-figures/references/debugging-without-vision.md
git commit -m "docs(plotly-interactive-figures): debugging-without-vision reference (three depths)"
```

---

### Task 9: `references/symptom-prescription.md`

**Files:**
- Create: `data-science/plotly-interactive-figures/references/symptom-prescription.md`

Grounded in the official docs `legend.md`, `axes.md`, `hover-text-and-formatting.md`, `setting-graph-size.md`, `colorscales.md`, `discrete-color.md`, `tick-formatting.md`, `figure-labels.md`, `figure-introspection.md`, `log-plot.md`.

- [ ] **Step 1: Write the reference**

```markdown
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
```

- [ ] **Step 2: Commit**

```bash
git add data-science/plotly-interactive-figures/references/symptom-prescription.md
git commit -m "docs(plotly-interactive-figures): symptom→prescription diagnosis table"
```

---

### Task 10: `references/px-patterns.md`

**Files:**
- Create: `data-science/plotly-interactive-figures/references/px-patterns.md`

One canonical `px` pattern per chart family, each authored to match the official docs and run through `pa.audit`. Grounded in `plotly-express.md` + the per-chart pages (`line-and-scatter.md`, `bar-charts.md`, `line-charts.md`, `histograms.md`, `box-plots.md`, `violin.md`, `heatmaps.md`).

- [ ] **Step 1: Write the reference**

````markdown
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
````

- [ ] **Step 2: Verify every pattern audits clean (run them)**

Run:
```bash
uv run --with plotly --with pandas python -c "
import sys; sys.path.insert(0,'data-science/plotly-interactive-figures/scripts')
import plotly_audit as pa, plotly.express as px, pandas as pd, numpy as np
df = pd.DataFrame({'category':[c for c in 'abc' for _ in range(8)],'price':[10,12,14,16,18,20,22,24,30,33,36,39,42,45,48,51,60,63,66,69,72,75,78,81],'sales':[5,8,6,9,4,7,5,6,4,3,5,7,6,4,5,8,3,6,4,7,5,6,4,8],'region':['N','S','E','W']*6})
figs = [
  px.scatter(df,x='price',y='sales',color='category',hover_data=['region']),
  px.bar(df.groupby('category',as_index=False)['sales'].sum(),x='category',y='sales',color='category'),
  px.line(pd.DataFrame({'t':range(6),'revenue':[1,3,2,5,4,6],'region':['N','N','S','S','E','E']}),x='t',y='revenue',color='region'),
  px.histogram(df,x='price',color='category',barmode='overlay',opacity=0.5),
  px.box(df,x='category',y='price',color='category'),
  px.violin(df,x='category',y='price',color='category',box=True),
  px.imshow(np.array([[1.0,0.8,-0.4],[0.8,1.0,0.2],[-0.4,0.2,1.0]])),
]
for i,f in enumerate(figs):
    fnd = [x for x in pa.audit(f) if x.severity in ('error','warn')]
    print(i, f.data[0].type, '->', [x.id for x in fnd] or 'clean')
"
```
Expected: every line prints `... -> clean` (no error/warn findings; the shipped patterns' `assert pa.audit(fig) == []` is stricter — also no `info` findings — keep the verify command and the asserts in sync). If any pattern triggers a finding, fix the pattern or the check.

- [ ] **Step 3: Commit**

```bash
git add data-science/plotly-interactive-figures/references/px-patterns.md
git commit -m "docs(plotly-interactive-figures): canonical px patterns, grounded + audited"
```

---

### Task 11: `references/notebook-delivery.md`

**Files:**
- Create: `data-science/plotly-interactive-figures/references/notebook-delivery.md`

- [ ] **Step 1: Write the reference**

````markdown
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
````

- [ ] **Step 2: Verify the assembly+execute recipe runs end-to-end**

Run:
```bash
uv run --with plotly --with pandas --with nbformat --with nbconvert python -c "
import nbformat as nbf
from nbformat.v4 import new_notebook, new_markdown_cell, new_code_cell
nb = new_notebook()
nb.cells = [
    new_markdown_cell('# t'),
    new_code_cell('import plotly.express as px; px.scatter(px.data.tips(), x=\"total_bill\", y=\"tip\").show()'),
]
nbf.write(nb, '/tmp/pif_nbtest.ipynb')
" && uv run --with plotly --with pandas --with nbconvert --with ipykernel jupyter nbconvert --to notebook --execute --inplace /tmp/pif_nbtest.ipynb && uv run --with nbformat python -c "
import nbformat
nb = nbformat.read('/tmp/pif_nbtest.ipynb', as_version=4)
out = nb.cells[1].get('outputs', [])
print('executed outputs:', len(out))
assert any("application/vnd.plotly.v1+json" in (o.get("data") or {}) for o in out), \
    'no plotly mime output — execution failed'
print('OK: figure embedded as cell output')
"
```
Expected: `executed outputs: 1` / `OK: figure embedded as cell output`.

- [ ] **Step 3: Commit**

```bash
git add data-science/plotly-interactive-figures/references/notebook-delivery.md
git commit -m "docs(plotly-interactive-figures): nbformat assembly + nbconvert execute recipe"
```

---

### Task 12: Full test suite + size check + trigger test + final commit

**Files:**
- Test: all `data-science/plotly-interactive-figures/tests/`

- [ ] **Step 1: Run the full suite**

Run: `uv run --with plotly --with pandas --with pytest python -m pytest data-science/plotly-interactive-figures/tests/ -v`
Expected: all PASS (35 tests: 6 entrypoint + 5 empty/dup + 6 cliponaxis/hover + 4 legend/colorway + 8 log/range + 6 margin).

- [ ] **Step 2: Size check**

Run: `./count-skill-tokens.py data-science/plotly-interactive-figures`
Expected: `SKILL.md` under 500 lines / ~5k tokens; `description` under ~100 tokens. Trim if it warns.

- [ ] **Step 3: Verify marketplace JSON + README consistency**

Run:
```bash
python -c "import json; d=json.load(open('.claude-plugin/marketplace.json')); ds=[p for p in d['plugins'] if p['name']=='data-science'][0]; assert './data-science/plotly-interactive-figures' in ds['skills']; print('marketplace ok')"
grep -c "plotly-interactive-figures" README.md
```
Expected: `marketplace ok`; README grep returns ≥1.

- [ ] **Step 4: Skill trigger test (manual, new session)**

Per repo `CLAUDE.md`: copy the skill to `~/.claude/skills/plotly-interactive-figures/`, start a fresh Claude Code session, and try prompts that should trigger ("make an interactive plotly scatter with hover", "this plotly figure looks wrong, debug it") and should not ("make a matplotlib publication figure", "keep an R session open"). Iterate on the `description` if triggering is unreliable.

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "test(plotly-interactive-figures): full audit suite + size + registration verified" --allow-empty
```

---

## Self-Review

**1. Spec coverage:**
- Three-depth verification (skeleton `to_dict` / full `full_figure_for_development` / vision `write_image`→`Read`) → Tasks 1–6 (audit = Depth 1) + Task 8 `debugging-without-vision.md` (all three depths + cliponaxis case + escalation ladder).
- 9 audit checks (empty trace, axis-range/data, legend off-canvas, missing hover, missing color, cliponaxis-on-text, duplicate names, margin, log-axis-zero) → Tasks 2–6. Note: the spec's "missing hover_data/hovertemplate" is implemented as the structurally-checkable `hover_disabled` (`hoverinfo='none'`); "missing color field/mapping" as `colorway_shorter_than_traces` (color reuse); "margin too small" as `margin_vs_edge_content` (edge annotation + tiny margin). These re-framings are because the to_dict skeleton exposes these concrete signals, not the user-intent phrasings — the user-intent versions live in `symptom-prescription.md` (Task 9). Documented in the checks' docstrings.
- `audit` accepts live Figure OR parsed `to_dict()` dict → Task 1 `_to_spec` + tests `test_audit_accepts_dict_spec_and_returns_list` / `test_audit_accepts_go_figure`.
- Kaleido as optional escalation, audit needs no Kaleido → Task 6 Step 5 (px clean smoke runs with `--with plotly --with pandas`, no kaleido) + Task 8 (escalation ladder).
- `.ipynb` deliverable (nbformat + nbconvert --execute, embed outputs, Write local) → Task 11 `notebook-delivery.md` + Step 2 end-to-end verify.
- 4 references grounded in official docs → Tasks 8–11, each with source URLs.
- Marketplace + README registration → Task 1 Steps 7–9 + Task 12 Step 3.
- Testing (pytest per locus-novelty precedent + size + trigger) → Tasks 1–6 (TDD) + Task 12.
- License/attribution (MIT; external/ plotly.py studied read-only, cite plotly.com URLs) → SKILL.md `license: MIT`; Conventions note in plan header; Task 8/9/10/11 cite plotly.com URLs.

**2. Deviation from spec (flagged, justified):** the design spec's `audit(fig_or_spec, df=None)` is implemented as `audit(fig_or_spec)` — the `df` parameter is dropped because Plotly Express expands the dataframe into `data[].x`/`data[].y` arrays in the `to_dict()` spec, so the skeleton is self-contained (the audit reads data values straight from the spec, no external df needed). The log-axis-zero and axis-range-excludes-data checks read `trace['x']`/`trace['y']` from the spec. This is a justified simplification; if a future figure references data not embedded in the spec, add `df` back then (YAGNI now).

**2b. `_to_spec` DataFrame guard (post-review fix):** `_to_spec` is dict-first and shape-checks `"data" in spec` on the duck-typed `to_dict()` output — `pandas.DataFrame` (which also has a `.to_dict()` whose output has no `"data"` key) is rejected with TypeError instead of silently auditing `{}`. Test: `test_audit_rejects_dataframe`. This false-clean hole was caught by the Task 1 code-quality review; keep the shape check whenever `_to_spec` is touched.

**2c. `cliponaxis_text` trace-type gate (post-review fix):** the check only fires on the cliponaxis-capable scatter family (trace `type` in `scatter`/`scatterpolar`/`scatterternary`, or an explicit `cliponaxis` in the skeleton) — Scattergl/Scatter3d/Scattergeo/Scattermap reject the property, so flagging them was a false warn whose fix hint (`update_traces(cliponaxis=False, ...)`) raises ValueError on those types. Also `mode` is read via `tr.get("mode") or ""` (handles `"mode": null` in hand-crafted specs). Tests: explicit-`cliponaxis=True` flagged, `Scattergl`-with-text not flagged, `hoverinfo="x+y"` not flagged.

**2d. `legend_off_canvas` bounded zones (implementer-caught plan bug):** the plan's original snippet used `x > 0.9` and `x < 0.05` (unbounded), which contradicts the plan's own negative test (`legend.x=1.05` must NOT be flagged) and would self-flag the check's fix-hint states. The implemented check bounds the danger zones to `0.9 < x < 1.0` and `0 < x < 0.05` — the straddling zone where the legend (extending rightward from `x` with `xanchor='left'`) hangs over the plot edge; `x >= 1.0` (e.g. Plotly's default `1.02`) sits wholly in the margin.

**2e. Typed-array decode + axis-binding filter (post-review fix, Task 5):** plotly 6.x serializes numpy-backed arrays in `to_dict()` as typed-array dicts `{"dtype","bdata"}` (verified with the skill's own test env: plotly 6.9.0), so `isinstance(v, (list, tuple))` gates silently skipped px-from-DataFrame data — the log-axis and axis-range checks were dead code on the primary path. `_decode_values` normalizes those dicts stdlib-only (base64 + `array` per `_DTYPE_SPEC`, float64 fallback), used by `_axis_vals` (which also filters traces to those bound to the inspected axis — x2/y2-bound traces no longer false-flag against `xaxis`/`yaxis`; subplot axes themselves remain a documented v1 limitation) and by `_check_empty_traces` (empty numpy traces now flagged). Regression tests: px-DataFrame `range_x` exclusion, px-DataFrame `log_y` zero, reversed-range original-order message, x2-binding no-false-positive, numpy-empty trace.

**2f. Margin check annotation `xref`/`yref` filter (post-review fix, Task 6):** the `near` filter requires an explicit paper reference (`a.get(ref_key) == "paper"` with the band table carrying the ref key). Evidence: plain `add_annotation` leaves `xref`/`yref` absent from the skeleton, and `full_figure_for_development()` (kaleido) shows the effective default is data coords (`'x'`) — so an absent key means data coords and is not edge-judgeable from the skeleton; only explicitly-paper annotations are flagged. A data-coord annotation whose value lands in 0.95–1.0 is inside the plot, not at the edge, and was falsely flagged with a fix hint pointing at the wrong margin. Subplot-paper references (`xref="x2 domain"`) remain a documented v1 limitation. Regression tests: data-coord annotation not flagged, paper annotation flagged, left band flagged, `margin.r=20` threshold boundary not flagged.

**3. Placeholder scan:** No "TBD"/"implement later"/"add error handling". Every code step shows complete code. Task 12 Step 4 (trigger test) is a concrete manual step per repo convention, not a placeholder. All reference content is complete (no "fill in the rest"). ✓

**4. Type consistency:** `Finding` fields (`id, severity, message, fix_hint, doc_ref`) and `as_dict()` defined in Task 1, used identically in Tasks 2–6. Check function signature `_check_*(spec: dict) -> list[Finding]` uniform across all checks. `_CHECKS` list grows by appending in Tasks 2–6 (final list: empty→+dup, +clip/hover, +legend/colorway, +log/range, +margin). `audit()`'s `for check in _CHECKS` loop (Task 1) consumes them uniformly. Test helper `_ids()` defined Task 1, used Tasks 2–6. `DOC = "https://plotly.com/python/"` constant (Task 1) used by every check's `doc_ref`. ✓

No issues found — plan ready.
