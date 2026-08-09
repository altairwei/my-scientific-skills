#!/usr/bin/env python3
# data-science/interactive-repl/scripts/discover.py
# Positron-style multi-source environment discovery for the interactive-repl
# skill. Scans every likely place a usable R or Python interpreter could live
# (PATH, conda envs, uv-managed pythons, system dirs), probes each candidate's
# version and the packages this skill needs, and reports which are READY.
#
# Modeled on posit-dev/positron's runtime discovery (rRuntimeDiscoverer +
# python-env-tools): many sources, per-candidate usability probes with
# timeouts, broken candidates degrade the report but never kill the scan,
# and a structured descriptor is emitted per environment so the agent (or a
# picker) can choose. Stdlib only — runs on any python3.
#
#   scripts/discover.py          human-readable report
#   scripts/discover.py --json   structured descriptors (JSON array on stdout)

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict

R_REQUIRED = ("jsonlite",)          # the worker's JSON protocol needs this
R_RECOMMENDED = ("knitr", "ggplot2")
PY_CHECKED = ("numpy", "pandas", "matplotlib")
R_SYSTEM_DIRS = (
    "/opt/R", "/usr/lib/R", "/usr/local/lib/R",
    "/usr/bin/R", "/usr/local/bin/R", "/opt/homebrew/bin/R",
)
PROBE_TIMEOUT = 20                  # per candidate probe (seconds)


@dataclass
class Candidate:
    language: str                   # "r" | "python"
    kind: str                       # "conda" | "system" | "uv" | "path"
    path: str                       # the binary (R/Rscript/python3)
    env_name: str = ""              # conda env name, if any
    version: str = ""
    packages: dict = field(default_factory=dict)   # {pkg: bool}
    usable: bool = False
    reason: str = ""

    def display_name(self) -> str:
        """Positron-style display name: 'R 4.3.3 (Conda: base)'."""
        lang = "R" if self.language == "r" else "Python"
        where = f" ({self.kind.title()}" + (f": {self.env_name}" if self.env_name else "") + ")"
        return f"{lang} {self.version}{where}"


# ---------------------------------------------------------------------------
# source enumeration
# ---------------------------------------------------------------------------

def _run(cmd, timeout=PROBE_TIMEOUT):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode, (r.stdout + r.stderr).strip()
    except (OSError, subprocess.TimeoutExpired):
        return -1, ""


def _conda_env_prefixes():
    """conda env list --json, falling back to ~/.conda/environments.txt
    (Positron's condaLocator does exactly this fallback)."""
    code, out = _run(["conda", "env", "list", "--json"], timeout=15)
    if code == 0:
        try:
            return [p for p in json.loads(out).get("envs", []) if p]
        except json.JSONDecodeError:
            pass
    txt = os.path.expanduser("~/.conda/environments.txt")
    if os.path.isfile(txt):
        try:
            return [l.strip() for l in open(txt) if l.strip()]
        except OSError:
            pass
    return []


def _conda_env_names(prefixes):
    """Map env prefixes to env names for display ('base' for the root)."""
    base = os.environ.get("CONDA_PREFIX")
    names = {}
    for p in prefixes:
        if base and os.path.realpath(p) == os.path.realpath(base):
            names[p] = "base"
        else:
            names[p] = os.path.basename(p)
    return names


def _system_r_bins():
    """Scan R system directories (RStudio/Positron conventions) + ad-hoc paths."""
    found = []
    for d in R_SYSTEM_DIRS:
        if os.path.isfile(d) and os.access(d, os.X_OK):
            found.append(d)
        elif os.path.isdir(d):
            # /opt/R/4.3.3/bin/R and the plain <dir>/bin/R forms
            for sub in (d, *[os.path.join(d, s) for s in os.listdir(d)]):
                b = os.path.join(sub, "bin", "R")
                if os.path.isfile(b) and os.access(b, os.X_OK):
                    found.append(b)
    return found


def _uv_python_bins():
    """uv-managed pythons (uv python dir → <ver>/bin/python3)."""
    if shutil.which("uv") is None:
        return []
    code, out = _run(["uv", "python", "dir"], timeout=10)
    if code != 0 or not out:
        return []
    root = out.strip().splitlines()[-1]
    if not os.path.isdir(root):
        return []
    bins = []
    for entry in os.listdir(root):
        b = os.path.join(root, entry, "bin", "python3")
        if os.path.isfile(b) and os.access(b, os.X_OK):
            bins.append(b)
    return bins


# ---------------------------------------------------------------------------
# probing
# ---------------------------------------------------------------------------

def _probe_r(path):
    c = Candidate(language="r", kind="?", path=path)
    code, out = _run([path, "--version"], timeout=10)
    if code != 0 or not out:
        c.reason = "Rscript not runnable"
        return c
    # handles both "R version 4.3.3" (R) and "Rscript (R) version 4.3.3"
    # (Debian's Rscript wrapper)
    m = re.search(r"version (\d+\.\d+(?:\.\d+)?)", out)
    if not m:
        c.reason = f"unparseable version: {out[:60]!r}"
        return c
    c.version = m.group(1)
    _, pkgs = _run([path, "-e", "cat(rownames(installed.packages()), sep=' ')"])
    present = set(pkgs.split())
    c.packages = {p: p in present for p in R_REQUIRED + R_RECOMMENDED}
    missing = [p for p in R_REQUIRED + R_RECOMMENDED if p not in present]
    if missing:
        c.reason = "missing packages: " + ", ".join(missing)
    else:
        c.usable = True
    return c


def _probe_python(path):
    c = Candidate(language="python", kind="?", path=path)
    code, out = _run([path, "-V"], timeout=10)
    if code != 0 or not out:
        c.reason = "python not runnable"
        return c
    m = re.search(r"Python (\S+)", out)
    if not m:
        c.reason = f"unparseable version: {out[:60]!r}"
        return c
    c.version = m.group(1)
    check = (
        "import importlib.util as u; "
        "print(all(u.find_spec(m) is not None for m in "
        + repr(list(PY_CHECKED)) + "))"
    )
    _, ok = _run([path, "-c", check], timeout=15)
    for p in PY_CHECKED:
        c.packages[p] = False
    if ok.strip() == "True":
        for p in PY_CHECKED:
            c.packages[p] = True
    # python deps are auto-installable via scripts/setup.sh — missing packages
    # do NOT make the candidate unusable, only noted.
    c.usable = True
    if not c.packages.get("numpy"):
        c.reason = "deps missing (installable via scripts/setup.sh)"
    return c


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------

def discover():
    cands: list[Candidate] = []
    seen = set()

    def add(c):
        rp = os.path.realpath(c.path)
        if rp in seen:
            return
        seen.add(rp)
        c.path = rp
        cands.append(c)

    # R sources: PATH → conda envs → system dirs
    for name in ("Rscript", "R"):
        p = shutil.which(name)
        if p:
            c = _probe_r(p)
            c.kind = "path"
            add(c)
    names = _conda_env_names(_conda_env_prefixes())
    for prefix in names:
        b = os.path.join(prefix, "bin", "R")
        if os.path.isfile(b) and os.access(b, os.X_OK):
            c = _probe_r(b)
            c.kind = "conda"
            c.env_name = names[prefix]
            add(c)
    for b in _system_r_bins():
        c = _probe_r(b)
        c.kind = "system"
        add(c)

    # Python sources: PATH → uv → conda envs
    for name in ("python3", "python"):
        p = shutil.which(name)
        if p:
            c = _probe_python(p)
            c.kind = "path"
            add(c)
    for b in _uv_python_bins():
        c = _probe_python(b)
        c.kind = "uv"
        add(c)
    for prefix in names:
        b = os.path.join(prefix, "bin", "python")
        if os.path.isfile(b) and os.access(b, os.X_OK):
            c = _probe_python(b)
            c.kind = "conda"
            c.env_name = names[prefix]
            add(c)

    # sort: usable first, then kind, then version desc
    kind_order = {"conda": 0, "uv": 1, "system": 2, "path": 3}
    cands.sort(key=lambda c: (not c.usable, kind_order.get(c.kind, 9),
                              tuple(int(x) for x in c.version.split(".")) if c.version else (0,), c.path))
    return cands


def _fmt_packages(c):
    parts = []
    for p, ok in c.packages.items():
        parts.append(p if ok else f"{p}!")
    return " ".join(parts) if parts else "-"


def print_report(cands):
    for lang, title in (("r", "R interpreters"), ("python", "Python interpreters")):
        print(title)
        for c in cands:
            if c.language != lang:
                continue
            mark = "READY" if c.usable else "  -- "
            note = c.reason if c.reason else "packages: " + _fmt_packages(c)
            print(f"  [{mark}] {c.display_name():<42} {c.path}")
            print(f"          {note}")
        print()
    print("Next steps")
    r_ready = [c for c in cands if c.language == "r" and c.usable]
    if r_ready:
        best = r_ready[0]
        if best.kind == "conda":
            print(f"  r: export INTERACTIVE_REPL_R_ENV={best.env_name}   "
                  f"(best candidate: {best.display_name()})")
        else:
            print(f"  r: export INTERACTIVE_REPL_R_BIN={best.path}   "
                  f"(best candidate: {best.display_name()})")
    else:
        creator = "mamba" if shutil.which("mamba") else ("conda" if shutil.which("conda") else "")
        if creator:
            print(f"  r: no usable R — create one: {creator} create -n r-env "
                  f"-c conda-forge r-base r-jsonlite r-knitr r-ggplot2")
        else:
            print("  r: no usable R and no conda/mamba — install R (see references/r-setup.md)")
    py_ready = [c for c in cands if c.language == "python" and c.usable]
    if not py_ready:
        print("  py: no python found — run scripts/setup.sh (installs uv + deps)")
    else:
        best = py_ready[0]
        missing = [p for p, ok in best.packages.items() if not ok]
        if missing:
            print(f"  py: best candidate {best.display_name()} lacks "
                  f"{', '.join(missing)} — run scripts/setup.sh to install them into py-site")
    print("  Write the chosen env into THIS project's .claude/settings.local.json "
          "(env section), e.g. {\"env\": {\"INTERACTIVE_REPL_R_ENV\": \"...\"}} — "
          "ask the user which env to use; never ~/.bashrc.")


def main():
    cands = discover()
    if "--json" in sys.argv[1:]:
        print(json.dumps([asdict(c) for c in cands], indent=2))
    else:
        print_report(cands)


if __name__ == "__main__":
    main()
