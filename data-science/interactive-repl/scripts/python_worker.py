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

Protocol channel: stdio pipes — local and slurm alike, because slurm runs this
worker via salloc+srun, which forwards the pipes to the compute node. Protocol
pipes are duped off fd 0/1 so user subprocesses inheriting them can't corrupt
the stream; real stdin/stdout → devnull. Errors are caught — the response
ALWAYS returns (no hangs). Adapted from wisp-science's kernel_worker.py.
"""
import builtins, io, json, os, resource, shutil, signal, subprocess, sys, time, traceback, uuid

# Force Agg BEFORE matplotlib is ever imported (so plt.show()/GUI backends can't block).
os.environ.setdefault("MPLBACKEND", "Agg")

MAX_OUTPUT = 1024 * 1024  # 1 MB head cap on stdout/stderr


class _CappedStringIO(io.StringIO):
    """StringIO with a write-time UTF-8 byte cap. A runaway print/logging loop
    otherwise grows the buffer unboundedly and can OOM the worker — the cap is
    enforced at write() time, not after the fact. getvalue() appends a marker
    reporting the REAL dropped count. Truncation never splits a UTF-8 sequence."""

    BUFFER_CAP = MAX_OUTPUT - 256  # headroom so marker + content fit under MAX_OUTPUT

    def __init__(self):
        super().__init__()
        self._buffered = 0
        self._dropped = 0

    def write(self, s):
        if self._buffered >= self.BUFFER_CAP:
            self._dropped += len(s.encode("utf-8", "surrogatepass"))
            return len(s)
        n = len(s.encode("utf-8", "surrogatepass"))
        remaining = self.BUFFER_CAP - self._buffered
        if n <= remaining:
            self._buffered += n
            return super().write(s)
        # Trim on a UTF-8 boundary: encode, slice bytes, decode.
        head = s.encode("utf-8", "surrogatepass")[:remaining].decode("utf-8", "ignore")
        self._buffered = self.BUFFER_CAP
        self._dropped = n - remaining
        super().write(head)
        return len(s)  # honour io.write contract (code points written-or-consumed)

    def getvalue(self):
        v = super().getvalue()
        if self._dropped:
            return v + (f"\n…(buffer capped at {self.BUFFER_CAP // 1024} KB; "
                        f"{self._dropped} further bytes dropped)\n")
        return v

    @property
    def truncated(self):
        return self._dropped > 0

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
    # Wheels are interpreter-ABI-specific — key the dir by interpreter version
    # so a worker launched with a different python (INTERACTIVE_REPL_PY_BIN)
    # never imports stale wrong-ABI wheels from another version's dir.
    ver = f"{sys.version_info.major}.{sys.version_info.minor}"
    d = os.path.join(_data_dir(), f"py-site-{ver}")
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
    # User code must never see the host's API keys (prompt-injection exfil
    # surface). Pop a static denylist from the WORKER's env only — never the
    # server's. Vars the worker needs (CLAUDE_PLUGIN_DATA, INTERACTIVE_REPL_*,
    # PATH, conda env vars, SLURM_*) are not in the list.
    for _k in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY",
               "OPENROUTER_API_KEY", "GITHUB_TOKEN", "HF_TOKEN",
               "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        os.environ.pop(_k, None)

    # Protocol channel: stdio pipes. Real stdin/stdout → devnull so user
    # subprocesses inheriting them can't corrupt the stream. The protocol fds
    # are explicitly non-inheritable (PEP 446 makes os.dup non-inheritable by
    # default; state the intent so a user subprocess can never hold the pipe
    # write-end open and wedge the server's EOF detection).
    protocol_in = os.fdopen(os.dup(0), "r", encoding="utf-8", errors="replace")
    protocol_out = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.set_inheritable(protocol_in.fileno(), False)
    os.set_inheritable(protocol_out.fileno(), False)
    os.dup2(os.open(os.devnull, os.O_RDONLY), 0)
    os.dup2(os.open(os.devnull, os.O_WRONLY), 1)

    import _common

    namespace = {"__name__": "__main__", "__builtins__": __builtins__}
    import json as _j, math, os as _os, re, sys as _sys
    namespace.update({"json": _j, "math": math, "os": _os, "re": re, "sys": _sys})

    # Shadow site.Quitter: the real exit()/quit() close sys.stdin before raising
    # SystemExit, killing the protocol channel. This quitter raises without
    # touching stdin; the marker subclass gates the hint so a library sys.exit()
    # is not blamed on REPL muscle memory.
    class _ReplQuitterExit(SystemExit):
        pass
    _ReplQuitterExit.__name__ = "SystemExit"
    _ReplQuitterExit.__qualname__ = "SystemExit"

    class _ReplQuitter:
        def __repr__(self):
            return ("exit()/quit() is disabled here — close the session with "
                    "the `close(session)` tool.")
        def __call__(self, code=None):
            raise _ReplQuitterExit(code)

    _quitter = _ReplQuitter()
    namespace["exit"] = namespace["quit"] = _quitter
    builtins.exit = builtins.quit = _quitter
    # A pre-populated py-site (scripts/setup.sh installs all runtime deps in
    # one shot) must be on sys.path from the start — otherwise the lazy-install
    # hook would re-fetch packages that are already there.
    _site = _py_site_dir()
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

    # Ready marker: SLURM job info (set by srun in slurm mode).
    protocol_out.write(_common.encode_line({
        "ready": True,
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
        _lc.cache.pop(f"<repl:{counter - 128}>", None)  # bound the cache

        out_cap, err_cap = _CappedStringIO(), _CappedStringIO()
        error = None
        interrupted = False
        old_out, old_err = sys.stdout, sys.stderr
        try:
            sys.stdout, sys.stderr = out_cap, err_cap
            _execute_cell(code, cell_tag, namespace)
        except BaseException as e:
            interrupted = bool(getattr(e, "_repl_delivered", False))
            error = traceback.format_exc()
            if isinstance(e, _ReplQuitterExit):
                error += ("\n(exit()/quit() is disabled here — close the session "
                          "with the `close(session)` tool.)")
        finally:
            sys.stdout, sys.stderr = old_out, old_err

        plots = _capture_new_figures()

        raw_stdout = out_cap.getvalue()
        raw_stderr = err_cap.getvalue()
        stdout = raw_stdout
        truncated = out_cap.truncated or err_cap.truncated
        degraded = not raw_stdout.strip() and bool(raw_stderr.strip())
        if degraded:
            stdout = _common.never_empty(stdout, raw_stderr)
        protocol_out.write(_common.encode_line({
            "id": rid, "stdout": stdout, "stderr": raw_stderr, "error": error,
            "plots": plots, "truncated": truncated, "degraded": degraded,
            "interrupted": interrupted}))
        protocol_out.flush()


if __name__ == "__main__":
    main()
