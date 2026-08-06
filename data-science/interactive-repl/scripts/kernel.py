"""Base interactive-repl sidecar — auto-injected into every python-repl session.

Definition-only, lazy imports (no side-effect code at load) — also the reference
example for sidecar authoring (see references/sidecar-authoring.md).
"""


def _who():
    """List session variables (name + type), excluding underscore-prefixed callables."""
    g = globals()
    return "\n".join(f"{n}\t{type(v).__name__}" for n, v in sorted(g.items())
                     if not n.startswith("_") and not callable(v))


def _peek(obj):
    """Type-dispatched summary: DataFrame → shape+dtypes+head; sized → len+repr; else repr."""
    t = type(obj).__name__
    if t == "DataFrame":
        return f"DataFrame {obj.shape}\n{obj.dtypes.to_string()}\n{obj.head()}"
    if hasattr(obj, "__len__"):
        return f"{t} len={len(obj)}\n{repr(obj)[:200]}"
    return repr(obj)[:200]


def _fig(n=0):
    """Return the path of the nth saved figure in this session's plot dir."""
    import os, glob
    import _common
    fs = sorted(glob.glob(os.path.join(_common.plot_dir(), "fig-*.png")))
    return fs[n] if fs else None
