"""Tests for scripts/discover.py — Positron-style env discovery.

Unit tests use fake R/python scripts (no real interpreters needed); the smoke
test runs the real script end-to-end (rc 0, both section headers present —
machine-independent even when no R/python exists).
"""
import json
import os
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import discover  # noqa: E402

FAKE_RS = """#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "R version 4.3.3 (2024-02-29)"
  echo "Platform: x86_64-pc-linux-gnu (64-bit)"
elif [ "$1" = "-e" ]; then
  echo "jsonlite knitr ggplot2"
fi
"""

FAKE_RS_NO_JSONLITE = """#!/bin/sh
if [ "$1" = "--version" ]; then
  echo "R version 4.3.3 (2024-02-29)"
elif [ "$1" = "-e" ]; then
  echo "knitr ggplot2"
fi
"""

FAKE_PY = """#!/bin/sh
if [ "$1" = "-V" ]; then
  echo "Python 3.12.3"
else
  echo "True"
fi
"""


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body)
    p.chmod(0o755)
    return str(p)


def test_conda_envs_txt_fallback(monkeypatch, tmp_path):
    """conda CLI absent → ~/.conda/environments.txt (Positron's condaLocator
    fallback)."""
    home = tmp_path / "home"
    (home / ".conda").mkdir(parents=True)
    (home / ".conda" / "environments.txt").write_text(
        "/opt/conda\n/home/u/envs/r-env\n")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("PATH", str(tmp_path))  # no conda on PATH
    assert discover._conda_env_prefixes() == ["/opt/conda", "/home/u/envs/r-env"]


def test_conda_env_names_marks_base(monkeypatch, tmp_path):
    monkeypatch.setenv("CONDA_PREFIX", "/opt/conda")
    names = discover._conda_env_names(["/opt/conda", "/home/u/envs/r-env"])
    assert names["/opt/conda"] == "base"
    assert names["/home/u/envs/r-env"] == "r-env"


def test_system_r_bins_finds_opt_R_layout(monkeypatch, tmp_path):
    r_dir = tmp_path / "opt" / "R" / "4.3.3" / "bin"
    r_dir.mkdir(parents=True)
    _write(r_dir, "R", "#!/bin/sh\nexit 0\n")
    monkeypatch.setattr(discover, "R_SYSTEM_DIRS", (str(tmp_path / "opt" / "R"),))
    assert discover._system_r_bins() == [str(r_dir / "R")]


def test_uv_python_bins(monkeypatch, tmp_path):
    uv_dir = tmp_path / "uvpythons"
    bin_dir = uv_dir / "cpython-3.11.15" / "bin"
    bin_dir.mkdir(parents=True)
    _write(bin_dir, "python3", "#!/bin/sh\nexit 0\n")
    shim = tmp_path / "uv"
    shim.write_text("#!/bin/sh\necho '" + str(uv_dir) + "'\n")
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    assert discover._uv_python_bins() == [str(bin_dir / "python3")]


def test_probe_r_usable_with_packages(monkeypatch, tmp_path):
    fake = _write(tmp_path, "Rscript", FAKE_RS)
    c = discover._probe_r(fake)
    assert c.version == "4.3.3"
    assert c.usable is True
    assert c.packages == {"jsonlite": True, "knitr": True, "ggplot2": True}


def test_probe_r_unusable_when_jsonlite_missing(monkeypatch, tmp_path):
    fake = _write(tmp_path, "Rscript", FAKE_RS_NO_JSONLITE)
    c = discover._probe_r(fake)
    assert c.version == "4.3.3"
    assert c.usable is False
    assert "jsonlite" in c.reason


def test_probe_python_usable_and_deps(monkeypatch, tmp_path):
    fake = _write(tmp_path, "python", FAKE_PY)
    c = discover._probe_python(fake)
    assert c.version == "3.12.3"
    assert c.usable is True
    assert all(c.packages.values())


def test_dedupe_by_realpath(monkeypatch, tmp_path):
    fake = _write(tmp_path, "Rscript", FAKE_RS)
    link = tmp_path / "Rlink"
    link.symlink_to(fake)
    a = discover._probe_r(fake)
    b = discover._probe_r(str(link))
    assert os.path.realpath(a.path) == os.path.realpath(b.path)


def test_discover_smoke_real_run(tmp_path):
    """End-to-end: rc 0, both section headers, --json parses as a list.
    Machine-independent — passes even with zero candidates found."""
    script = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "discover.py"
    r = subprocess.run([sys.executable, str(script)], capture_output=True, text=True,
                       timeout=180)
    assert r.returncode == 0, r.stderr
    assert "R interpreters" in r.stdout
    assert "Python interpreters" in r.stdout
    rj = subprocess.run([sys.executable, str(script), "--json"], capture_output=True,
                        text=True, timeout=180)
    assert rj.returncode == 0
    assert isinstance(json.loads(rj.stdout), list)
