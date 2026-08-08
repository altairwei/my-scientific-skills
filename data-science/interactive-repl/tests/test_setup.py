"""Sanity checks for scripts/setup.sh (the one-shot dep installer)."""
import pathlib
import subprocess

SETUP = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "setup.sh"


def test_setup_sh_syntax():
    r = subprocess.run(["bash", "-n", str(SETUP)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_setup_sh_executable():
    assert SETUP.stat().st_mode & 0o111, "setup.sh must be executable"
