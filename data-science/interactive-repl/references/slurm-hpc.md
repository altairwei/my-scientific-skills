# HPC / Slurm — run REPL workers on compute nodes

At HPC centers, login nodes must not run long or compute-heavy work — compute
belongs on a compute node allocated via `srun`. This skill can launch each REPL
worker inside an srun allocation and talk to it across the network. Off by
default; activate via `worker_mode()` (runtime) or `INTERACTIVE_REPL_SLURM`
(persistent).

## When to use

- The task is heavy (big joins, training, simulations) and the host is a login node.
- The user mentions 超算/集群/slurm/srun/sbatch/队列/配额/partition.
- `worker_mode()` reports `probe.srun_available: true` and the task is heavy.

## Decision flow — call `worker_mode()` with no args first

1. `probe.srun_available: false` → stay `local`; tell the user this host has no Slurm.
2. `probe.already_in_allocation: true` → stay `local` — Claude Code is already
   running inside a job; a nested srun allocation is pointless.
3. Otherwise, for heavy work → `worker_mode(mode="slurm")`. Flags: use the
   user's partition/account/cpus/mem if they told you, else pass nothing
   (keeps the env default).
4. Session over / task turned light → `worker_mode(mode="local")` to stop
   submitting jobs.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `INTERACTIVE_REPL_SLURM` | unset | srun flags, e.g. `--partition=compute --account=acct -c 16 --mem=64G`. Non-empty → all sessions of this server launch via srun. |
| `INTERACTIVE_REPL_TRANSPORT` | `direct` | `direct` (worker connects to the login node) or `tunnel` (worker runs `ssh -fN -L` back to the login node). |
| `INTERACTIVE_REPL_HOST` | `hostname` | Login-node hostname as seen from compute nodes; also the tunnel's ssh target. |
| `INTERACTIVE_REPL_SRUN_TIMEOUT` | `300` | Max queue wait + startup (seconds). |

`worker_mode()` overrides all of these at runtime (per server process); tool
settings beat env vars, apply to sessions created after the switch, and reset
when the server restarts.

## Prerequisites — read before using

1. **`CLAUDE_PLUGIN_DATA` must point at shared storage.** The default
   `/tmp/interactive-repl-data` is per-node: plots saved on a compute node
   would be invisible on the login node, and the lazy-install `py-site` would
   be built twice. Export it to a shared path (e.g. under your home) before
   using slurm mode.
2. Login and compute nodes share home (standard on HPC) — this is what makes
   the worker scripts, the uv-managed python, R/conda envs, `uv`, and ssh keys
   available on the compute node.
3. Direct transport: compute nodes must reach the login node's TCP ports. If
   not, set `INTERACTIVE_REPL_TRANSPORT=tunnel` — the worker then needs
   passwordless ssh from the compute node to the login node (shared home
   usually provides it).

## Semantics

- **First call blocks**: `run_code` auto-creates the session, which submits
  the srun job and waits for the allocation (`INTERACTIVE_REPL_SRUN_TIMEOUT`).
  Queue wait is real — tell the user the session is queued.
- **Allocation expiry ≈ data loss.** srun's `-t` bounds the session. When the
  allocation ends the connection drops — `run_code` returns `worker died`;
  `restart(session)` resubmits (a fresh namespace). Size `-t` for the work.
- **`restart`** scancels the old job and resubmits under the current mode.
- **`session_info`** reports `job_id` / `node` / `transport` — tell the user
  where the session runs ("on cn042, job 74213").
- **Switching modes** only affects new sessions; existing sessions keep
  running until restarted.
- **Security**: slurm sessions carry a token handshake, so other users of the
  shared login node cannot inject code into the bound port.

## Common failures

- `srun allocation did not start within 300s` — flags wrong (bad
  partition/account) or queue busy; check `squeue`, fix flags, retry.
- `worker died` mid-session — allocation expired or was preempted → `restart`.
- Tunnel mode fails at session start — ssh from the compute node to the login
  node must be passwordless; check `~/.ssh` keys on the shared home.
- Plots not readable after slurm sessions — `CLAUDE_PLUGIN_DATA` is not on
  shared storage (see Prerequisites).

## Escape hatch

Run the entire Claude Code inside `srun --pty` — everything stays localhost
and zero configuration is needed. Use it when the whole session belongs on a
compute node; use slurm mode when you work on the login node and compute on
nodes.
