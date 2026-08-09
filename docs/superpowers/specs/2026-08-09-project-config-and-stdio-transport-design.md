# Project-scoped env config + stdio-only transport

Date: 2026-08-09
Status: design (user-approved 2026-08-09)

## 1. Background — two failures found in real-world setup

The user set up this skill on a fresh host and hit two design defects:

**1. User-level config pollution.** SKILL.md Setup step 3 directed the agent to
"persist it yourself (append the export to `~/.bashrc`)" and discover.py
auto-picked the best READY candidate — no user involvement. Conda envs are
project-scoped (one env per project), so writing the choice into the user's
global shell config leaks it into every other project on the machine.

**2. Slurm TCP machinery.** The MCP↔worker channel on HPC is three layers of
TCP plumbing: a login-node listener + a token handshake (open port on a shared
node = injection risk) + a dual direct/tunnel transport + an ssh reverse
tunnel. Humans don't do this: `salloc` a resource, then `srun` a worker — srun
already forwards the worker's stdio to the client. Local R also runs TCP
(R's socketConnection is TCP-only — the original excuse), and the same
verification showed R stdio is fully workable.

## 2. Design 1 — project-scoped environment config

### 2.1 The setup flow (rewrites SKILL.md Setup step 3)

1. The agent runs `scripts/discover.py` and gets the candidate list (conda
   envs / PATH / uv pythons / system dirs, with READY markers).
2. **The agent asks the user** — R: which conda env or R path; Python: which
   conda env's python, or the server default.
3. The choice is written to the **project-level** `.claude/settings.local.json`
   `env` section (`INTERACTIVE_REPL_R_ENV` / `INTERACTIVE_REPL_R_BIN` /
   `INTERACTIVE_REPL_PY_BIN`). Claude Code applies these to the session
   process; spawned MCP servers (and their workers) inherit them. No shell
   config is touched.
4. The agent asks whether the user also wants a user-level copy (default: no).
5. The user restarts Claude Code (env is read at launch — unchanged UX).

Why `settings.local.json` over `settings.json`: env names are machine-specific
and must not be committed; `settings.local.json` is the local, personal
channel. A team that genuinely shares env names can still add
`settings.json` themselves.

### 2.2 New config key: `INTERACTIVE_REPL_PY_BIN`

The py worker command becomes env-overridable: `[PY_BIN, WORKER]` when set,
else `[sys.executable, WORKER]` (unchanged default). Conda-env pythons are
plain binaries — no `conda run` wrapper needed (unlike R, whose library
resolution needs env activation).

### 2.3 py-site becomes interpreter-versioned

Wheels in `py-site` are ABI-specific (built for the interpreter that ran
`uv pip install`). A worker launched with a different interpreter would import
the stale wrong-ABI wheels and fail with `ImportError` — **not**
`ModuleNotFoundError`, so the lazy-install hook cannot rescue it. Fix:

- Worker uses `py-site-<major>.<minor>` (e.g. `py-site-3.11`), created on
  demand; the lazy-install hook targets it.
- `setup.sh` installs into the versioned dir of the interpreter it runs
  (querying the same interpreter `uv run` resolves), keeping the one-shot
  pre-warm property.
- The legacy `py-site` dir is left in place, unused, deprecated.

## 3. Design 2 — stdio-only transport (TCP removed everywhere)

### 3.1 R worker stdio mode (validated empirically 2026-08-09)

The R worker's protocol moves off the socket onto pipes:

- **Requests:** `readLines(file("stdin"), n = 1)` — blocks on the pipe, EOF →
  `character(0)` → break (server-death self-reap, same as today).
- **Responses:** `cat(json, "\n", sep="", file="")` + `flush(stdout())`.
  Sink windows are per-cell (`sink(out_con, type="output")` during eval only),
  so protocol writes happen outside any sink — never captured. Verified.
- **Warnings:** captured with `withCallingHandlers(warning=…)` — collect the
  message and `invokeRestart("muffleWarning")` so execution continues; they
  surface in the response's `stderr` field (currently always `""`).
  **Not** `sink(type="message")` — empirically broken (silent process death,
  and it captures `stderr()` writes too).
- **Launch:** `R --quiet --no-echo --no-save --no-restore -f repl.R` —
  `--no-echo` kills the source echo R prints to stdout for `-f` scripts.
- **Residual risk, contained:** a user `system()`/child-process writing to
  fd 1 leaks raw lines onto the protocol stream → the server's tolerant
  reader (below) skips non-JSON lines. (The old design had the same hole for
  R — its fd 1 was an unread pipe — so no regression.)

### 3.2 Server: one launch path, tolerant reader

- `_start` has a single Popen(stdio pipes) path for every language and mode;
  the slurm branch only changes the argv: `salloc <flags> srun <flags>
  <worker>` (flags on both — salloc allocates, srun's step matches, and a
  bare `srun <flags> <worker>` is used when already inside an allocation, per
  the probe). Ready handshake over stdout as today; job_id/node still come
  from the worker's `SLURM_JOB_ID`/`SLURM_JOB_NODELIST` env.
- `_recv` becomes a tolerant reader: read lines, skip anything that isn't
  valid JSON, return the line whose `id` matches the request (covers R
  child-process output and any banner noise; srun/salloc banners land on
  stderr, which never touches the protocol).
- `_send`/`_recv`/`Session` lose the `conn` branch — `Session.conn` deleted.

### 3.3 Deletions

- Env machinery: `REPL_PORT` / `REPL_TOKEN` / `REPL_HOST` /
  `REPL_TRANSPORT` (server, python_worker.py, repl.R).
- Token handshake (stdio pipes are private — no open port, no injection
  surface).
- `_slurm`: `launch_remote` → `launch` (salloc chain, queue-timeout hint
  kept), `tunnel_cmd`, `transport()`, `new_token`, `ssh_available` probe
  key (ssh no longer needed anywhere).
- Registry `tcp` flag (all workers are stdio).
- Tool surface: `session_info.transport` field and `worker_mode`'s
  `transport` argument (dead concepts). `WorkerModeInfo.host` too.
- `_kill` simplifies: scancel (job_id from ready handshake) + terminate —
  the `conn` close branch goes.

### 3.4 python worker

The `REPL_PORT` branches (TCP connect + tunnel) are deleted; the worker is
pure stdio always. The fd-dup of 0/1 to devnull (children can't corrupt the
protocol) stays — this is what makes the python side need no tolerant
reader.

## 4. Tests

- **Delete:** `test_tunnel_python_end_to_end`, `test_tunnel_r_end_to_end`,
  `test_python_worker`'s TCP-mode test.
- **New:** R stdio roundtrip via the real R worker; R warning → `stderr`
  field; slurm salloc→srun chain (fake `salloc` shim added next to the fake
  `srun`); tolerant-reader (garbage line skipped, matching-id response
  returned); py-site version-keyed dir used by the worker; `session_info`
  has no `transport`; `worker_mode` rejects/ignores `transport`.
- **Update:** r-server tests (no REPL_PORT launch), smoke tests, worker_mode
  tests (signature), setup.sh test (versioned py-site), discover/setup docs
  assertions.

## 5. Docs

- `SKILL.md`: Setup step 3 rewritten (discover → ask → write
  `settings.local.json` → restart); `worker_mode`/`session_info` tool
  descriptions drop transport; mention `INTERACTIVE_REPL_PY_BIN` in setup;
  slurm section updated (salloc + srun, no tunnel).
- `references/tools.md`: `session_info` / `worker_mode` signatures.
- `references/slurm-hpc.md`: rewritten — salloc chain, stdio, no ssh tunnel,
  no token.
- `references/r-setup.md`: R worker now stdio (protocol notes).

## 6. Trade-offs

| Decision | Cost / rationale |
|---|---|
| `settings.local.json` | Machine-scoped, not committed — correct for env names; a team can opt into `settings.json` themselves |
| Full TCP removal | R `stderr` field now carries warnings (improvement); child-process fd-1 noise handled by the tolerant reader; `cat(file=stderr())` from user code would corrupt R's protocol (rare, documented) |
| Always ask the user | No auto-pick shortcuts — one extra interaction at setup, correct env choice guaranteed |
| py-site versioning | `setup.sh` installs per-interpreter dir; legacy `py-site` abandoned in place |
| One flags string for salloc+srun | Slight redundancy (srun repeats allocation flags) vs one config knob |

## 7. Out of scope

- No auto-detection without asking; no config beyond env vars.
- Session naming, the 9 tools' other signatures, chunk routing, plot
  handling, sidecars — unchanged.
- discover.py discovery sources unchanged (only its guidance text).
- No back-compat aliases for `transport` (zero external references).
