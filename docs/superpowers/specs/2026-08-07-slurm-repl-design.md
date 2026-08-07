# Slurm / HPC Worker Launch — Design

**Date:** 2026-08-07
**Status:** Approved (all 5 design sections reviewed by user)

## Problem

`interactive-repl` spawns its R/Python workers as local subprocesses of the MCP
servers (which run inside Claude Code on the login node). At HPC centers with a
Slurm scheduler, login nodes must not run long or compute-heavy work — the
worker (the part that executes user code) must run on a compute node allocated
via `srun`. The skill currently has no support for this: there is no way to
move a REPL session onto a compute node.

## Decisions (user-approved)

1. **Form — srun interactive.** One `srun` allocation per REPL session;
   allocation lifetime = session lifetime. Session ends / server exits → the
   job is released (no leaked quotas). Crash or allocation expiry surfaces as
   the existing `worker died` error → `restart(session)` resubmits. (No
   sbatch attach/detach in v1 — the REPL state dies with the allocation.)
2. **Transport — compute→login callback, two configurable flavors.**
   - *direct*: server binds `0.0.0.0:0` on the login node; worker connects to
     `REPL_HOST:REPL_PORT` across the interconnect.
   - *tunnel*: server binds `127.0.0.1:0`; worker runs
     `ssh -fN -L <L>:localhost:<port> <login>` on the compute node, then
     connects to `localhost:L` (home is shared, so compute→login ssh almost
     always works even when direct TCP is firewalled).
   Both modes carry a **token handshake** — login nodes are shared machines and
   an open port is a code-injection risk.
3. **Trigger — env default + agent-runtime tool.** `INTERACTIVE_REPL_SLURM`
   (srun flags) is the user's persistent default. A new MCP tool `worker_mode`
   lets the agent probe the environment and switch modes at runtime. When
   slurm is in effect, **all** sessions of that server go to compute nodes.
   No config = local mode, byte-for-byte the current behavior.

## Architecture

```
Login node (Claude Code process)                    Compute node (srun allocation)
┌──────────────────────────────┐                   ┌──────────────────────────┐
│ MCP server (stdio)           │                   │ worker                   │
│ _start(): if slurm mode      │                   │  R: repl.R (already a    │
│   bind listener (0.0.0.0 or  │                   │     TCP client)          │
│   127.0.0.1)                 │                   │  Py: python_worker.py    │
│   token = secrets.token_hex  │                   │     (gains TCP-client    │
│   srun <flags> <worker cmd> ─┼──────────────────▶│     path; pipes stay)   │
│   accept + validate token ◀──┼───────────────────┤ env: REPL_HOST/PORT/     │
│                              │                   │      TOKEN/TRANSPORT     │
│ _call_worker() unchanged     │                   │ ready{token, job_id,     │
│                              │                   │        node}             │
└──────────────────────────────┘                   └──────────────────────────┘
```

Local mode: unchanged — python via stdin/stdout pipes, R via localhost TCP, no
token, no srun.

### New shared module `scripts/_slurm.py` (~100 lines)

Both servers already share `_common` / `_chunk_parser`; `_slurm.py` is the
third shared helper. It encapsulates all slurm mechanics:

- `launch_remote(worker_cmd: list[str]) -> (Popen, socket, meta)` — the whole
  remote-start flow: transport resolution → bind → token → srun spawn → accept
  with timeout → ready read → token validation → returns
  `meta = {transport, job_id, node}`. Raises `RuntimeError` with a queue-hint
  message on timeout and a `token mismatch` error on validation failure.
- `srun_cmd(flags: str, cmd: list[str]) -> list[str]` — `["srun", *shlex.split(flags), *cmd]`.
- `new_token() -> str` — `secrets.token_hex(16)`.
- `login_host() -> str` — `INTERACTIVE_REPL_HOST` or `socket.gethostname()`.
- `srun_timeout() -> int` — `INTERACTIVE_REPL_SRUN_TIMEOUT`, default 300.
- `tunnel_cmd(local: int, login: str, remote: int) -> list[str]` —
  `ssh -fN -L <local>:localhost:<remote> <login> -o BatchMode=yes -o
  ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ConnectTimeout=10`.
- `probe() -> dict` — `{srun_available, already_in_allocation, ssh_available}`
  via `shutil.which` + `SLURM_JOB_ID` check; used by `worker_mode()`.
- `flags() -> str` / `transport() -> str` — runtime override (tool-set) falling
  back to env, falling back to defaults. Source reported for transparency.

### `python_worker.py` — TCP-client path (~12 lines in `main()`)

If `REPL_PORT` is set in the environment, the protocol channel becomes a socket
instead of pipes; otherwise everything is as today:

```python
port = os.environ.get("REPL_PORT")
if port:
    host = os.environ.get("REPL_HOST", "localhost")
    if os.environ.get("REPL_TRANSPORT") == "tunnel":
        # 1) pick free local port L (bind 127.0.0.1:0, read, close)
        # 2) subprocess.run(tunnel_cmd(L, host, int(port)), check=True)
        #    (exit 0 ⇒ tunnel up; non-zero ⇒ ssh auth/bind failure — fail fast)
        # 3) conn = socket.create_connection(("127.0.0.1", L), timeout=30)
    else:
        conn = socket.create_connection((host, int(port)), timeout=30)
    protocol_in  = conn.makefile("r", encoding="utf-8", errors="replace")
    protocol_out = conn.makefile("w", encoding="utf-8", buffering=1)
    # keep the existing fd 0/1 → devnull dup2 (user subprocess hygiene)
else:
    # existing os.dup(0)/dup(1) pipes path
```

Ready message gains `token` (from `REPL_TOKEN` env) and
`job_id`/`node` (from `SLURM_JOB_ID` / `SLURM_JOB_NODELIST`, set by srun).

### `repl.R` — host env + tunnel + token (~25 lines)

- Connection: `host <- Sys.getenv("REPL_HOST", "localhost")` (was hardcoded).
- Tunnel branch: pick a free high port L (random in 20000–40000 with a
  `socketConnection` probe-retry loop, ~5 attempts — base R cannot read an
  OS-assigned `port=0`), then
  `system2("ssh", c("-fN", "-L", "<L>:localhost:<REPL_PORT>", host,
  "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
  "-o", "ServerAliveInterval=30", "-o", "ConnectTimeout=10"), wait=TRUE)` —
  `-f` means the foreground exits quickly either way, so the exit status is a
  deterministic tunnel-ready check (bind collision → retry with new L; auth
  failure → exit non-zero → worker exits → server accept-timeout with tunnel
  hint).
- Ready message: `list(ready=TRUE, token=Sys.getenv("REPL_TOKEN", ""),
  job_id=Sys.getenv("SLURM_JOB_ID"), node=Sys.getenv("SLURM_JOB_NODELIST"))`.

### Servers (`python_repl_server.py` / `r_repl_server.py`)

- `_start(session)`: in slurm mode, delegate to `_slurm.launch_remote()` with
  the worker command, then do the sidecar inject as today. Local mode path
  unchanged.
- `restart(session)`: slurm mode = best-effort `scancel <job_id>` (if known)
  + terminate the srun Popen + resubmit. Local unchanged. The resubmit follows
  the **currently effective** worker mode.
- `session_info(session)`: new fields `job_id`, `node`, `transport`
  (`"local" | "direct" | "tunnel"`), stored from `launch_remote` meta.
- New tool `worker_mode` (see below).

## Config & trigger

### Env vars (user's persistent default; all optional, all default = today)

| Variable | Default | Meaning |
|---|---|---|
| `INTERACTIVE_REPL_SLURM` | unset | **Master switch.** srun flags string, e.g. `--partition=compute --account=acct -c 16 --mem=64G`. Non-empty → all sessions of this server launch via srun; unset → local mode. |
| `INTERACTIVE_REPL_TRANSPORT` | `direct` | `direct` or `tunnel` |
| `INTERACTIVE_REPL_HOST` | `socket.gethostname()` | Login-node hostname as seen from compute nodes (also the tunnel's ssh target) |
| `INTERACTIVE_REPL_SRUN_TIMEOUT` | `300` | accept timeout (seconds) for queue wait + startup |

### `worker_mode` tool (both servers, each manages its own)

```
worker_mode(mode?, slurm_flags?, transport?) → WorkerModeInfo
```

- **No args = probe + report.** Returns the currently effective config plus
  environment detection, so the agent can decide:

```json
{
  "mode": "local",                    // current effective mode
  "source": "env",                    // "env" | "tool" (where mode came from)
  "slurm_flags": "--partition=compute --account=acct -c 16 --mem=64G",
  "transport": "direct",
  "host": "login01",
  "timeout": 300,
  "probe": {
    "srun_available": true,           // command -v srun
    "already_in_allocation": false,   // SLURM_JOB_ID set ⇒ inside a job already
    "ssh_available": true             // command -v ssh (tunnel prerequisite)
  }
}
```

- **With args = runtime switch** (this server process only; server restart
  falls back to env defaults): `mode="local"|"slurm"`;
  `slurm_flags` overrides env (empty string = keep env); `transport`
  overrides `direct`/`tunnel`. **Precedence: tool > env > built-in default.**
- Switching affects only sessions created **after** the switch; existing
  sessions keep running under their launch-time mode until `restart`.

### Skill decision logic (documented in `references/slurm-hpc.md`, short section in SKILL.md)

1. Task involves heavy compute / long loops, or the user mentions cluster /
   超算 / login node / srun / 队列 → call `worker_mode()` first.
2. `probe.srun_available: false` → stay `local`, tell the user this host has no
   Slurm.
3. `probe.already_in_allocation: true` → stay `local` — Claude Code is already
   running inside a job; nested srun is pointless.
4. Otherwise → recommend `mode="slurm"`; `slurm_flags` = user-provided
   partition/account when known, else `""` (keep env default) or the env value.
5. Session over / task turned light → switch back to `mode="local"`.
6. Direct-mode session start error → recommend `transport="tunnel"` retry.

This also covers the zero-config scenario: the agent detects a login node with
srun and heavy work, decides to go compute itself, and tells the user.

## Error handling & ops

- **Queue / startup timeout** (accept timeout): terminate the srun Popen (the
  queued job is cancelled with it) and report:
  `srun allocation did not start within 300s — check slurm flags and queue
  status (squeue). First run_code blocks until the allocation starts.`
- **Allocation expiry / preemption mid-session**: connection breaks → existing
  `worker died` path → `restart` resubmits. Expiry ≈ data loss — docs say to
  size `-t` for the session up front.
- **Tunnel failure** (ssh auth/BatchMode/bind): worker exits early → accept
  timeout with a hint to check passwordless ssh to the login node.
- **Token mismatch**: close the connection, report `token mismatch`, no session
  created.
- **`session_info`**: reports `job_id` / `node` / `transport` — the agent can
  tell the user "session on cn042, job 74213".

### Shared-storage requirements (ops-critical, documented)

- `CLAUDE_PLUGIN_DATA` must point at **shared storage** — the default
  `/tmp/interactive-repl-data` is per-node, so compute-node plots and the
  lazy-install `py-site` would be invisible on the login node. Top warning in
  the reference doc.
- `uv` must be on the compute node's PATH (shared-home `~/.local/bin/uv`
  satisfies this).
- Compute-node R/python (conda env, Rscript) must match the login node — shared
  home usually guarantees this.
- `run_chunk` cwd semantics are unchanged (shared home ⇒ notebook paths resolve
  identically on both nodes).

### Escape hatch (documented)

Run the entire Claude Code inside `srun --pty` — everything stays localhost,
zero config. Complementary to the env/tool approach (whole-session-on-node vs
login-node-office + compute-node-work).

## Testing

1. **Python worker TCP mode** (extend `tests/test_python_worker.py`): local
   listener + `REPL_PORT`/`REPL_HOST`/`REPL_TOKEN` env → ready carries
   token + job info; protocol roundtrip works.
2. **Fake `srun` shim integration** (new `tests/test_slurm.py`, both servers):
   a fake `srun` script on a tmp PATH logs argv/env, injects
   `SLURM_JOB_ID=4242` / `SLURM_JOB_NODELIST=cn042`, then `exec "$@"` forwards
   the real worker command. With `INTERACTIVE_REPL_SLURM` set: `run_code`
   end-to-end works, `session_info` reports job_id/node/transport, `restart`
   invokes a fake `scancel` (second shim).
3. **Fake `ssh` tunnel integration**: a fake `ssh` python shim parses
   `-L L:localhost:P`, listens on L, proxies to localhost:P — the full tunnel
   path runs end-to-end without real ssh.
4. **`worker_mode` tool tests**: probe fields present; `set slurm` routes new
   sessions through the shim; existing sessions unaffected by a switch;
   empty `slurm_flags` keeps env defaults; fresh server instance resets state.
5. **Local-mode regression**: all 93 existing tests stay green — local paths
   are untouched (hard constraint).

## Docs

- `references/slurm-hpc.md` (new): env table, `worker_mode` decision logic,
  prerequisites (shared-storage warning first), queue/expiry semantics, escape
  hatch, common failures (allocation timeout, tunnel auth, plots not readable).
- `SKILL.md`: `worker_mode` bullet in the tools list + a short "HPC / Slurm"
  section pointing at the reference. `description` unchanged (token budget).
- `references/troubleshooting.md`: slurm entries (allocation timeout, tunnel
  failure, plots missing).
- `README.md`: one line on HPC/Slurm support.

## Out of scope (v1)

- sbatch attach/detach sessions (future work)
- multi-node workers (assume `srun -N1`; user flags may override at their own risk)
- per-session mode override (mode is server-level)
- non-Linux login nodes
- login-node → compute-node direct connections (universally blocked; callback only)
- PBS/LSF/other schedulers (Slurm only)
