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


# ── cliponaxis + text ──────────────────────────────────────────────────────────

def test_text_trace_cliponaxis_flagged():
    fig = go.Figure(go.Scatter(x=[1, 2], y=[1, 2], text=["a", "b"], mode="markers+text"))
    assert "cliponaxis_text" in _ids(pa.audit(fig))


def test_cliponaxis_false_not_flagged():
    fig = go.Figure(go.Scatter(x=[1, 2], y=[1, 2], text=["a", "b"],
                               mode="markers+text", cliponaxis=False))
    assert "cliponaxis_text" not in _ids(pa.audit(fig))


def test_explicit_cliponaxis_true_flagged():
    fig = go.Figure(go.Scatter(x=[1], y=[1], text=["a"], mode="markers+text", cliponaxis=True))
    assert "cliponaxis_text" in _ids(pa.audit(fig))


def test_scattergl_with_text_not_flagged():
    # Scattergl has no cliponaxis property — flagging it would be a false positive
    fig = go.Figure(go.Scattergl(x=[1], y=[1], text=["a"], mode="markers+text"))
    assert "cliponaxis_text" not in _ids(pa.audit(fig))


def test_hoverinfo_limited_not_flagged():
    fig = go.Figure(go.Scatter(x=[1], y=[1], hoverinfo="x+y"))
    assert "hover_disabled" not in _ids(pa.audit(fig))


# ── hover disabled ─────────────────────────────────────────────────────────────

def test_hoverinfo_none_flagged():
    fig = go.Figure(go.Scatter(x=[1], y=[1], hoverinfo="none"))
    assert "hover_disabled" in _ids(pa.audit(fig))


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


# ── typed-array (plotly 6.x numpy) + axis binding ─────────────────────────────

def test_px_dataframe_manual_range_excluding_data_flagged():
    import pandas as pd
    import plotly.express as px
    df = pd.DataFrame({"x": [1, 2, 3, 4], "y": [1, 2, 3, 4]})
    fig = px.scatter(df, x="x", y="y")
    fig.update_xaxes(range=[0, 3])   # x=4 outside; numpy-backed data in plotly 6.x
    assert "axis_range_excludes_data" in _ids(pa.audit(fig))


def test_px_dataframe_log_axis_zero_flagged():
    import pandas as pd
    import plotly.express as px
    df = pd.DataFrame({"x": [1, 2, 3], "y": [1, 0, 4]})
    fig = px.scatter(df, x="x", y="y", log_y=True)
    assert "log_axis_nonpositive" in _ids(pa.audit(fig))


def test_reversed_range_excluding_data_flagged():
    fig = go.Figure(go.Scatter(x=[1, 2, 3, 5], y=[1, 2, 3, 5]))
    fig.update_xaxes(range=[4, 1])
    finds = [f for f in pa.audit(fig) if f.id == "axis_range_excludes_data"]
    assert finds and "range=[4,1]" in finds[0].message   # original order shown


def test_x2_bound_trace_not_falsely_flagged():
    fig = go.Figure([go.Scatter(x=[1, 2], y=[1, 2]),
                     go.Scatter(x=[100, 200], y=[1, 2], xaxis="x2")])
    fig.update_xaxes(range=[0, 10])
    assert "axis_range_excludes_data" not in _ids(pa.audit(fig))


def test_numpy_empty_trace_flagged():
    import numpy as np
    fig = go.Figure(go.Scatter(x=np.array([]), y=np.array([])))
    assert "empty_trace" in _ids(pa.audit(fig))
