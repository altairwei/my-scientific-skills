#!/usr/bin/env python3
# data-science/interactive-repl/scripts/python_worker.py
# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "matplotlib", "pandas"]
# ///
"""Persistent Python namespace over a JSON-per-line stdin/stdout protocol.

Request:  {"id": "<rid>", "code": "<python source>"}
Response: {"id": "<rid>", "stdout": "...", "stderr": "...", "error": null|"<traceback>",
           "plots": ["/path/to/fig.png"], "truncated": false, "degraded": false}

Protocol pipes are duped off fd 0/1 so user subprocesses inheriting them can't
corrupt the stream; real stdin/stdout → devnull. Errors are caught — the response
ALWAYS returns (no hangs). Adapted from wisp-science's kernel_worker.py.
"""
import builtins, io, json, os, sys, traceback, uuid

# Force Agg BEFORE matplotlib is ever imported (so plt.show()/GUI backends can't block).
os.environ.setdefault("MPLBACKEND", "Agg")

MAX_OUTPUT = 1024 * 1024  # 1 MB head cap on stdout/stderr

_EXEC_PREFIXES = ("import ", "from ", "def ", "class ", "if ", "for ", "while ",
                  "with ", "try:", "try ", "except ", "finally:", "elif ", "else:",
                  "raise ", "return ", "del ", "global ", "nonlocal ", "assert ",
                  "async ", "match ", "case ", "yield ", "@")


def _looks_like_exec(code: str) -> bool:
    s = code.strip()
    if not s or "\n" in s:
        return True
    return any(s.lstrip().startswith(p) for p in _EXEC_PREFIXES)


def _execute_cell(code, cell_tag, namespace):
    """Run one cell as eval (expression, prints repr) or exec (statements)."""
    if _looks_like_exec(code):
        exec(compile(code, cell_tag, "exec"), namespace)
        return
    try:
        result = eval(compile(code, cell_tag, "eval"), namespace)
    except SyntaxError:
        exec(compile(code, cell_tag, "exec"), namespace)
        return
    if result is not None:
        print(repr(result))


def _configure_pandas():
    """Set pandas display options on first import (uses sys.modules — no re-import)."""
    pd = sys.modules.get("pandas")
    if pd is None:
        return
    try:
        pd.set_option("display.max_columns", None)
        pd.set_option("display.max_rows", 500)
        pd.set_option("display.max_colwidth", None)
        pd.set_option("display.width", None)
        pd.set_option("display.expand_frame_repr", False)
    except Exception:
        pass


def _neutralize_pyplot_show():
    """Make plt.show() a no-op so a GUI backend can't block the worker."""
    plt = sys.modules.get("matplotlib.pyplot")
    if plt is None:
        return
    show = getattr(plt, "show", None)
    if show is None or getattr(show, "_repl_noop", False):
        return
    def _noop(*_a, **_k):
        return None
    _noop._repl_noop = True
    plt.show = _noop


def _capture_new_figures():
    """Save any new matplotlib figures to the plot dir; return paths; close them."""
    try:
        import matplotlib.pyplot as plt
    except Exception:
        return []
    nums = plt.get_fignums()
    if not nums:
        return []
    import _common
    pdir = _common.plot_dir()
    paths = []
    for n in nums:
        fig = plt.figure(n)
        path = os.path.join(pdir, f"fig-{n}-{uuid.uuid4().hex[:8]}.png")
        try:
            fig.savefig(path, dpi=110, bbox_inches="tight")
            paths.append(path)
        except Exception:
            pass
        plt.close(fig)
    return paths


def main():
    # Move protocol pipes off fd 0/1 so user subprocesses inheriting them can't
    # corrupt the stream. Real stdin/stdout → devnull.
    protocol_in = os.fdopen(os.dup(0), "r", encoding="utf-8", errors="replace")
    protocol_out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)

    import _common

    namespace = {"__name__": "__main__", "__builtins__": __builtins__}
    import json as _j, math, os as _os, re, sys as _sys
    namespace.update({"json": _j, "math": math, "os": _os, "re": re, "sys": _sys})
    for mod in ("numpy", "pandas"):
        try:
            namespace[mod] = __import__(mod)
        except ImportError:
            pass
    if "pandas" in namespace:
        _configure_pandas()

    # Lazy import hook: configure pandas / neutralize plt.show on first import.
    _orig_import = builtins.__import__
    def import_wrapper(name, *a, **k):
        mod = _orig_import(name, *a, **k)
        try:
            if name == "pandas":
                _configure_pandas()
            elif name.startswith("matplotlib"):
                _neutralize_pyplot_show()
        except Exception:
            pass
        return mod
    builtins.__import__ = import_wrapper

    import linecache as _lc
    counter = 0

    # Ready marker on the protocol channel.
    protocol_out.write(_common.encode_line({"ready": True}))
    protocol_out.flush()

    while True:
        line = protocol_in.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            protocol_out.write(_common.encode_line({
                "id": "unknown", "stdout": "", "stderr": "",
                "error": f"Invalid JSON: {e}", "plots": [],
                "truncated": False, "degraded": False}))
            protocol_out.flush()
            continue
        rid = req.get("id", "unknown")
        code = req.get("code", "")
        counter += 1
        cell_tag = f"<repl:{counter}>"
        _lc.cache[cell_tag] = (len(code), None, code.splitlines(True), cell_tag)

        out_cap, err_cap = io.StringIO(), io.StringIO()
        error = None
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = out_cap, err_cap
            _execute_cell(code, cell_tag, namespace)
        except BaseException:
            error = traceback.format_exc()
        finally:
            sys.stdout, sys.stderr = old_out, old_err

        plots = _capture_new_figures()

        raw_stdout = out_cap.getvalue()
        raw_stderr = err_cap.getvalue()
        stdout, truncated = _common.cap_output(raw_stdout)
        degraded = not raw_stdout.strip() and bool(raw_stderr.strip())
        if degraded:
            stdout = _common.never_empty(stdout, raw_stderr)
        protocol_out.write(_common.encode_line({
            "id": rid, "stdout": stdout, "stderr": raw_stderr, "error": error,
            "plots": plots, "truncated": truncated, "degraded": degraded}))
        protocol_out.flush()


if __name__ == "__main__":
    main()
