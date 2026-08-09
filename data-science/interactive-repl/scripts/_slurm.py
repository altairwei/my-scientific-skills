#!/usr/bin/env python3
# Shared Slurm/HPC launch helpers for the repl MCP server.
#
# Slurm mode is active when INTERACTIVE_REPL_SLURM (srun flags string) is set
# or the worker_mode tool overrode the mode. A worker is launched as
# `salloc <flags> srun <flags> <worker cmd>`: salloc holds the allocation, srun
# forwards the worker's stdio pipes to the login node, so the JSON protocol
# rides plain pipes — no ports, no tokens, no ssh tunnels. Already inside an
# allocation (SLURM_JOB_ID set): a bare `srun` attaches to it.
"""Slurm launch helpers: launch, probe, config resolution."""
import os, shlex, shutil, subprocess

_DEFAULT_TIMEOUT = 300
_runtime: dict = {}  # worker_mode tool overrides: {"mode", "flags"}


def set_runtime(mode=None, flags=None):
    """Record worker_mode tool overrides. "" / None = no override (keep env)."""
    if mode is not None:
        _runtime["mode"] = mode
    if flags:
        _runtime["flags"] = flags


def reset_runtime():
    """Drop tool overrides (fresh server instance = env defaults again)."""
    _runtime.clear()


def slurm_enabled() -> bool:
    """True if sessions should launch via salloc/srun. A tool mode override
    beats env; mode="local" disables slurm even when INTERACTIVE_REPL_SLURM
    is set."""
    if "mode" in _runtime:
        return _runtime["mode"] == "slurm"
    return bool(os.environ.get("INTERACTIVE_REPL_SLURM"))


def flags() -> str:
    return _runtime.get("flags", os.environ.get("INTERACTIVE_REPL_SLURM", ""))


def srun_timeout() -> int:
    try:
        return int(os.environ.get("INTERACTIVE_REPL_SRUN_TIMEOUT", _DEFAULT_TIMEOUT))
    except ValueError:
        return _DEFAULT_TIMEOUT


def srun_cmd(flags_str: str, cmd: list[str]) -> list[str]:
    return ["srun", *shlex.split(flags_str), *cmd]


def probe() -> dict:
    """Environment detection for the worker_mode tool's decision logic."""
    return {
        "srun_available": shutil.which("srun") is not None,
        "already_in_allocation": bool(os.environ.get("SLURM_JOB_ID")),
    }


def launch(worker_cmd: list[str]) -> subprocess.Popen:
    """Launch a worker on a compute node: `salloc <flags> srun <flags>
    <worker>` (or bare `srun <flags> <worker>` when already inside an
    allocation). srun forwards the worker's stdio pipes, so the JSON protocol
    rides them unchanged. Returns the Popen; the server reads the ready
    handshake with the srun_timeout deadline (queue wait)."""
    if os.environ.get("SLURM_JOB_ID"):
        argv = srun_cmd(flags(), worker_cmd)
    else:
        argv = ["salloc", *shlex.split(flags()), *srun_cmd(flags(), worker_cmd)]
    try:
        return subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, bufsize=1)
    except OSError as e:
        raise RuntimeError(f"could not launch {argv[0]}: {e}")
