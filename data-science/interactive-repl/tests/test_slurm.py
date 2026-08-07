import os
import re
import socket
import sys
import pathlib
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import _slurm  # noqa: E402


def test_srun_cmd_parses_flags():
    assert _slurm.srun_cmd("--partition=a -c 8", ["python", "w.py"]) == \
        ["srun", "--partition=a", "-c", "8", "python", "w.py"]


def test_srun_cmd_empty_flags():
    assert _slurm.srun_cmd("", ["x"]) == ["srun", "x"]


def test_new_token_is_32_hex_chars():
    assert re.fullmatch(r"[0-9a-f]{32}", _slurm.new_token())


def test_login_host_env_override(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_REPL_HOST", "my-login")
    assert _slurm.login_host() == "my-login"


def test_login_host_defaults_to_gethostname(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_REPL_HOST", raising=False)
    assert _slurm.login_host() == socket.gethostname()


def test_srun_timeout_default_and_parse(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_REPL_SRUN_TIMEOUT", raising=False)
    assert _slurm.srun_timeout() == 300
    monkeypatch.setenv("INTERACTIVE_REPL_SRUN_TIMEOUT", "600")
    assert _slurm.srun_timeout() == 600
    monkeypatch.setenv("INTERACTIVE_REPL_SRUN_TIMEOUT", "abc")
    assert _slurm.srun_timeout() == 300


def test_tunnel_cmd_argv():
    cmd = _slurm.tunnel_cmd(43210, "login01", 45678)
    assert cmd[0] == "ssh"
    assert "-L" in cmd
    assert "43210:localhost:45678" in cmd
    assert "login01" in cmd
    assert "BatchMode=yes" in cmd
    assert "ExitOnForwardFailure=yes" in cmd


def test_slurm_enabled_env(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_REPL_SLURM", raising=False)
    _slurm.reset_runtime()
    assert _slurm.slurm_enabled() is False
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=test")
    assert _slurm.slurm_enabled() is True


def test_runtime_mode_local_overrides_env(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=test")
    _slurm.set_runtime(mode="local")
    assert _slurm.slurm_enabled() is False
    _slurm.reset_runtime()
    assert _slurm.slurm_enabled() is True


def test_flags_precedence_runtime_over_env(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=env")
    _slurm.reset_runtime()
    assert _slurm.flags() == "--partition=env"
    _slurm.set_runtime(flags="--partition=tool")
    assert _slurm.flags() == "--partition=tool"
    _slurm.reset_runtime()
    assert _slurm.flags() == "--partition=env"


def test_flags_empty_or_none_keeps_env(monkeypatch):
    monkeypatch.setenv("INTERACTIVE_REPL_SLURM", "--partition=env")
    _slurm.reset_runtime()
    _slurm.set_runtime(flags="")
    assert _slurm.flags() == "--partition=env"   # empty string = keep env (spec)
    _slurm.set_runtime(flags=None)
    assert _slurm.flags() == "--partition=env"


def test_transport_default_and_override(monkeypatch):
    monkeypatch.delenv("INTERACTIVE_REPL_TRANSPORT", raising=False)
    _slurm.reset_runtime()
    assert _slurm.transport() == "direct"
    monkeypatch.setenv("INTERACTIVE_REPL_TRANSPORT", "tunnel")
    assert _slurm.transport() == "tunnel"
    _slurm.set_runtime(transport="direct")
    assert _slurm.transport() == "direct"   # tool beats env
    _slurm.reset_runtime()


def test_probe_fields(monkeypatch, tmp_path):
    srun_shim = tmp_path / "srun"
    srun_shim.write_text("#!/bin/sh\nexit 0\n")
    srun_shim.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    monkeypatch.delenv("SLURM_JOB_ID", raising=False)
    p = _slurm.probe()
    assert p["srun_available"] is True
    assert p["already_in_allocation"] is False
    monkeypatch.setenv("SLURM_JOB_ID", "1234")
    assert _slurm.probe()["already_in_allocation"] is True
