# HPC / Slurm — run REPL workers on compute nodes

At HPC centers, login nodes must not run long or compute-heavy work — compute
belongs on a compute node. This skill launches each REPL worker via
`salloc <flags> srun <flags> <worker>`: salloc holds the allocation, srun
forwards the worker's stdio pipes to the login node, so the JSON protocol
rides plain pipes — no ports, no tokens, no ssh tunnels. Off by default;
activate via `worker_mode()` (runtime) or `INTERACTIVE_REPL_SLURM` (persistent).

## When to use

- The task is heavy (big joins, training, simulations) and the host is a login node.
- The user mentions 超算/集群/slurm/srun/sbatch/队列/配额/partition.
- `worker_mode()` reports `probe.srun_available: true` and the task is heavy.

## Decision flow — call `worker_mode()` with no args first

1. `probe.srun_available: false` → stay `local`; tell the user this host has no Slurm.
2. `probe.already_in_allocation: true` → the server launches a bare `srun` —
   Claude Code is already inside a job; the worker attaches to the allocation.
3. Otherwise, for heavy work → `worker_mode(mode="slurm")`. Flags: use the
   user's partition/account/cpus/mem if they told you, else pass nothing
   (keeps the env default).
4. Session over / task turned light → `worker_mode(mode="local")` to stop
   submitting jobs.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `INTERACTIVE_REPL_SLURM` | unset | salloc/srun flags, e.g. `--partition=compute --account=acct -c 16 --mem=64G`. Non-empty → all sessions of this server launch via salloc+srun. |
| `INTERACTIVE_REPL_SRUN_TIMEOUT` | `300` | Max queue wait + startup (seconds). |

`worker_mode()` overrides at runtime (per server process); tool settings beat
env vars, apply to sessions created after the switch, and reset when the
server restarts.

## Prerequisites — read before using

1. **The data dir must be on shared storage — and it is, by default.** Plots
   and the lazy-install `py-site-<ver>` live under `CLAUDE_PLUGIN_DATA`, which
   the plugin launcher injects at `~/.claude/plugins/data/<plugin>` (not
   user-overridable). On standard HPC that path is under your home, which is
   shared across nodes — compute-node workers see the same files, so nothing
   to configure. Only a non-standard setup where home is NOT shared across
   nodes needs intervention (symlink the dir to shared storage as a
   workaround).
2. Login and compute nodes share home (standard on HPC) — this is what makes
   the worker scripts, the uv-managed python, R/conda envs and `uv` available
   on the compute node. No ssh or port-forwarding setup is needed: srun
   carries the stdio itself.

## Semantics

- **First call blocks**: `run_code` auto-creates the session, which submits
  the salloc+srun chain and waits for the allocation
  (`INTERACTIVE_REPL_SRUN_TIMEOUT`). Queue wait is real — tell the user the
  session is queued.
- **Allocation expiry ≈ data loss.** The allocation's time limit bounds the
  session. When the allocation ends the pipes close — `run_code` returns
  `worker died`; `restart(session)` resubmits (a fresh namespace). Size the
  allocation for the work.
- **`restart` / `close`** scancel the old job (job id from the worker's ready
  handshake) and kill the salloc process.
- **`session_info`** reports `job_id` / `node` — tell the user where the
  session runs ("on cn042, job 74213").
- **Switching modes** only affects new sessions; existing sessions keep
  running until restarted.

## Common failures

- `salloc allocation did not start within 300s` — flags wrong (bad
  partition/account) or queue busy; check `squeue`, fix flags, retry.
- `worker died` mid-session — allocation expired or was preempted → `restart`.
- Plots not readable after slurm sessions — the home (and with it
  `~/.claude/plugins/data`) is not shared across nodes (see Prerequisites).

## Escape hatch

Run the entire Claude Code inside `srun --pty` — everything stays localhost
and zero configuration is needed. Use it when the whole session belongs on a
compute node; use slurm mode when you work on the login node and compute on
nodes.
