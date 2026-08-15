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


def _check_cliponaxis_text(spec: dict) -> list[Finding]:
    # cliponaxis defaults to True (per the official figure-introspection doc); text
    # labels crossing an axis line are clipped when it's True.
    out = []
    for i, tr in enumerate(_traces(spec)):
        mode = tr.get("mode", "")
        if "text" not in mode:
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


_CHECKS = [_check_empty_traces, _check_duplicate_names,
           _check_cliponaxis_text, _check_hover_disabled]
