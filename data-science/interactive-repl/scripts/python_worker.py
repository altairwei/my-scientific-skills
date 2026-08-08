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
import builtins, io, json, os, shutil, subprocess, sys, traceback, uuid

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
    """Save any new matplotlib figures to the plot dir; return paths; close them.
    Uses sys.modules (not a fresh import) so we don't trigger a lazy-install of
    matplotlib when the user hasn't plotted — only capture figures the user created."""
    plt = sys.modules.get("matplotlib.pyplot")
    if plt is None:
        return []  # user never imported matplotlib → no figures to capture
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


# Heavy data-science deps are NOT in the server's startup env (only mcp+pydantic are).
# On first import, fetch the missing top-level package into a persistent dir via
# `uv pip install --target` (reuses uv's wheel cache → fast after the first time) and
# add it to sys.path so the retry import finds it.
_LAZY_PKGS = {"numpy": "numpy", "pandas": "pandas", "matplotlib": "matplotlib"}


def _data_dir():
    return os.environ.get("CLAUDE_PLUGIN_DATA") or "/tmp/interactive-repl-data"


def _py_site_dir():
    d = os.path.join(_data_dir(), "py-site")
    os.makedirs(d, exist_ok=True)
    return d


def _uv_bin():
    return shutil.which("uv") or "uv"


def _lazy_install(top):
    target = _py_site_dir()
    if target not in sys.path:
        sys.path.insert(0, target)
    try:
        subprocess.run([_uv_bin(), "pip", "install", "--target", target,
                        _LAZY_PKGS.get(top, top)],
                       check=True, capture_output=True, timeout=120)
        return True
    except Exception:
        return False


def _make_import_wrapper(_orig_import):
    """Wrap builtins.__import__: on ModuleNotFoundError for a lazy pkg, install it
    into py-site and retry; configure pandas / neutralize plt.show on first import."""
    def import_wrapper(name, *a, **k):
        try:
            mod = _orig_import(name, *a, **k)
        except ModuleNotFoundError:
            top = name.split(".")[0]
            if top in _LAZY_PKGS and _lazy_install(top):
                mod = _orig_import(name, *a, **k)  # retry; py-site now on sys.path
            else:
                raise
        try:
            if name == "pandas":
                _configure_pandas()
            elif name.startswith("matplotlib"):
                _neutralize_pyplot_show()
        except Exception:
            pass
        return mod
    return import_wrapper


def main():
    # Protocol channel: TCP client when REPL_PORT is set (slurm/compute-node
    # mode, launched via srun), else stdin/stdout pipes (local mode). Real
    # stdin/stdout → devnull in both cases so user subprocesses inheriting
    # them can't corrupt the stream.
    port = os.environ.get("REPL_PORT")
    if port:
        import socket as _sock
        import _slurm
        host = os.environ.get("REPL_HOST", "localhost")
        if os.environ.get("REPL_TRANSPORT") == "tunnel":
            # ssh -fN -L <L>:localhost:<port> forwards the server's listener
            # to this node; pick a free local port first. The foreground ssh
            # exits 0 once the tunnel is up (check=True) — non-zero means
            # bind collision / auth failure → fail fast.
            s = _sock.socket()
            s.bind(("127.0.0.1", 0))
            local_port = s.getsockname()[1]
            s.close()
            subprocess.run(_slurm.tunnel_cmd(local_port, host, int(port)),
                           check=True, timeout=30)
            conn = _sock.create_connection(("127.0.0.1", local_port), timeout=30)
        else:
            conn = _sock.create_connection((host, int(port)), timeout=30)
        protocol_in = conn.makefile("r", encoding="utf-8", errors="replace")
        protocol_out = conn.makefile("w", encoding="utf-8", buffering=1)
    else:
        protocol_in = os.fdopen(os.dup(0), "r", encoding="utf-8", errors="replace")
        protocol_out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)

    import _common

    namespace = {"__name__": "__main__", "__builtins__": __builtins__}
    import json as _j, math, os as _os, re, sys as _sys
    namespace.update({"json": _j, "math": math, "os": _os, "re": re, "sys": _sys})
    # A pre-populated py-site (scripts/setup.sh installs all runtime deps in
    # one shot) must be on sys.path from the start — otherwise the lazy-install
    # hook would re-fetch packages that are already there.
    _site = os.path.join(_data_dir(), "py-site")
    if os.path.isdir(_site) and os.listdir(_site):
        sys.path.insert(0, _site)
    # Install the lazy-import hook BEFORE pre-importing numpy/pandas, so a missing
    # dep is fetched into py-site on first use (the server starts with only mcp+pydantic).
    builtins.__import__ = _make_import_wrapper(builtins.__import__)

    for mod in ("numpy", "pandas"):
        try:
            namespace[mod] = __import__(mod)
        except ImportError:
            pass
    if "pandas" in namespace:
        _configure_pandas()

    import linecache as _lc
    counter = 0

    # Ready marker: token (validated by the server in slurm mode — an open
    # port on a shared login node is an injection risk) + SLURM job info.
    protocol_out.write(_common.encode_line({
        "ready": True,
        "token": os.environ.get("REPL_TOKEN", ""),
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "node": os.environ.get("SLURM_JOB_NODELIST"),
    }))
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
