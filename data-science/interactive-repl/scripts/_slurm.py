#!/usr/bin/env python3
# data-science/interactive-repl/scripts/_slurm.py
# Shared Slurm/HPC launch helpers for the python-repl and r-repl MCP servers.
#
# Slurm mode is active when INTERACTIVE_REPL_SLURM (srun flags string) is set
# or the worker_mode tool overrode the mode. A worker is launched with
# `srun <flags> <worker cmd>`; the server binds a TCP listener, passes
# REPL_HOST/REPL_PORT/REPL_TOKEN/REPL_TRANSPORT via env, and validates the
# token in the worker's ready handshake (login nodes are shared machines — an
# open port is a code-injection risk). Transport: "direct" = worker connects
# to the login node's bound port; "tunnel" = worker runs `ssh -fN -L` on the
# compute node and connects through it.
"""Slurm launch helpers: launch_remote, tunnel_cmd, probe, config resolution."""
import json, os, secrets, shlex, shutil, socket, subprocess

_DEFAULT_TIMEOUT = 300
_runtime: dict = {}  # worker_mode tool overrides: {"mode", "flags", "transport"}


def set_runtime(mode=None, flags=None, transport=None):
    """Record worker_mode tool overrides. "" / None = no override (keep env)."""
    if mode is not None:
        _runtime["mode"] = mode
    if flags:
        _runtime["flags"] = flags
    if transport:
        _runtime["transport"] = transport


def reset_runtime():
    """Drop tool overrides (fresh server instance = env defaults again)."""
    _runtime.clear()


def slurm_enabled() -> bool:
    """True if sessions should launch via srun. A tool mode override beats env;
    mode="local" disables slurm even when INTERACTIVE_REPL_SLURM is set."""
    if "mode" in _runtime:
        return _runtime["mode"] == "slurm"
    return bool(os.environ.get("INTERACTIVE_REPL_SLURM"))


def flags() -> str:
    return _runtime.get("flags", os.environ.get("INTERACTIVE_REPL_SLURM", ""))


def transport() -> str:
    return _runtime.get("transport", os.environ.get("INTERACTIVE_REPL_TRANSPORT", "direct"))


def login_host() -> str:
    return os.environ.get("INTERACTIVE_REPL_HOST") or socket.gethostname()


def srun_timeout() -> int:
    try:
        return int(os.environ.get("INTERACTIVE_REPL_SRUN_TIMEOUT", _DEFAULT_TIMEOUT))
    except ValueError:
        return _DEFAULT_TIMEOUT


def new_token() -> str:
    return secrets.token_hex(16)


def srun_cmd(flags_str: str, cmd: list[str]) -> list[str]:
    return ["srun", *shlex.split(flags_str), *cmd]


def tunnel_cmd(local_port: int, login: str, remote_port: int) -> list[str]:
    """`ssh -fN -L <local>:localhost:<remote> <login>` — run on the COMPUTE node
    so connections to the compute node's localhost:<local> reach the server's
    listener on the login node. -f backgrounds after the tunnel is established,
    so the process exits 0 quickly on success; BatchMode forbids password
    prompts (jobs are non-interactive); ExitOnForwardFailure surfaces a bind
    collision as a non-zero exit."""
    return ["ssh", "-fN", "-L", f"{local_port}:localhost:{remote_port}", login,
            "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
            "-o", "ServerAliveInterval=30", "-o", "ConnectTimeout=10"]


def probe() -> dict:
    """Environment detection for the worker_mode tool's decision logic."""
    return {
        "srun_available": shutil.which("srun") is not None,
        "already_in_allocation": bool(os.environ.get("SLURM_JOB_ID")),
        "ssh_available": shutil.which("ssh") is not None,
    }


def launch_remote(worker_cmd: list[str]) -> tuple:
    """srun-launch a worker and complete the callback handshake.

    Returns (proc, conn, meta) — conn is the accepted protocol socket, meta =
    {"transport", "job_id", "node"} (job info from the worker's ready message,
    which reads SLURM_JOB_ID / SLURM_JOB_NODELIST set by srun). Raises
    RuntimeError with a queue hint on accept timeout, or a token-mismatch error
    on handshake failure (possible unauthorized connection to the bound port)."""
    t = transport()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("0.0.0.0" if t == "direct" else "127.0.0.1", 0))
    srv.listen(1)
    srv.settimeout(srun_timeout())
    port = srv.getsockname()[1]
    token = new_token()
    env = {**os.environ, "REPL_PORT": str(port), "REPL_TOKEN": token,
           "REPL_HOST": login_host(), "REPL_TRANSPORT": t}
    proc = subprocess.Popen(srun_cmd(flags(), worker_cmd), env=env)
    try:
        conn, _ = srv.accept()
    except (socket.timeout, TimeoutError):
        try:
            proc.terminate()
        except Exception:
            pass
        raise RuntimeError(
            f"srun allocation did not start within {srun_timeout()}s — check "
            f"INTERACTIVE_REPL_SLURM flags and queue status (squeue). First "
            f"call blocks until the allocation starts.")
    finally:
        srv.close()
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = conn.recv(65536)
        if not chunk:
            proc.terminate()
            raise RuntimeError("worker exited before ready handshake (tunnel/ssh failure?)")
        buf += chunk
    ready = json.loads(buf.decode())
    if ready.get("token") != token:
        conn.close()
        proc.terminate()
        raise RuntimeError("token mismatch — possible unauthorized connection; session not created")
    if not ready.get("ready"):
        conn.close()
        proc.terminate()
        raise RuntimeError(f"worker failed to start: {ready!r}")
    meta = {"transport": t, "job_id": ready.get("job_id"), "node": ready.get("node")}
    return proc, conn, meta
