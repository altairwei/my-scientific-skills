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
        print(f"[{f.severity}] {f.id}: {f.message}\n  fix: {f.fix_hint}\n  ref: {f.doc_ref}")
    # or audit a pasted spec the user printed:
    pa.audit(fig.to_dict())

Run tests:

    uv run --with plotly --with pandas --with pytest \
        python -m pytest data-science/plotly-interactive-figures/tests/ -v

`doc_ref` values point at https://plotly.com/python/<slug>/. See the skill's
references/debugging-without-vision.md for the three-depth model this audit is the
first depth of.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import array
import base64

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


def _check_empty_traces(spec: dict) -> list[Finding]:
    out = []
    for i, tr in enumerate(_traces(spec)):
        for axis in ("x", "y", "z", "values", "labels"):
            v = _decode_values(tr.get(axis))
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


def _check_margin_vs_edge_content(spec: dict) -> list[Finding]:
    # A small margin on a side that has paper-coord content (annotation near the
    # edge) risks clipping. Axis-title clipping can't be checked from the skeleton
    # (its rendered position is a Plotly.js default) — that goes to the
    # full_figure_for_development escalation, not this check.
    out = []
    layout = _layout(spec)
    margin = layout.get("margin", {}) or {}
    anns = layout.get("annotations", []) or []
    edges = [("right", "r", 0.95, 1.0, "x"), ("left", "l", 0.0, 0.05, "x"),
             ("top", "t", 0.95, 1.0, "y"), ("bottom", "b", 0.0, 0.05, "y")]
    for side, mkey, lo, hi, anchor_axis in edges:
        m = margin.get(mkey)
        if m is None or m >= 20:
            continue
        near = [a for a in anns if _is_num(a.get(anchor_axis)) and lo <= a[anchor_axis] <= hi]
        if near:
            out.append(Finding(f"margin_{side}_edge", "info",
                f"margin.{mkey}={m} but {len(near)} annotation(s) sit at the {side} edge (paper {lo}-{hi}) — may be clipped",
                f"fig.update_layout(margin=dict({mkey}=40)) to reserve space for edge content",
                DOC + "setting-graph-size/"))
    return out


_CHECKS = [_check_empty_traces, _check_duplicate_names,
           _check_cliponaxis_text, _check_hover_disabled,
           _check_legend_off_canvas, _check_colorway_short,
           _check_log_axis_nonpositive, _check_axis_range_excludes_data,
           _check_margin_vs_edge_content]
