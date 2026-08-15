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
