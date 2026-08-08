# `close(session)` tool — explicit session teardown

Date: 2026-08-08
Status: design (user-approved 2026-08-08)

## 1. Background: the missing half of the lifecycle

The `repl` MCP server manages worker lifecycle as spawn → proxy → die. What it
cannot do is **deliberately end a session**:

- The tool surface (8 tools) has no close/stop/delete — the only destructive
  operation is `restart`, which kills **and immediately respawns**.
- There is no idle TTL and no other reaper: `_sessions` is a plain dict, never
  pruned. A session lives until the server process exits (a Claude Code
  restart), because the skill's value proposition is persistence ("survives
  compaction").
- Consequences: workers accumulate over a long session (one process per ever-
  touched `r:<name>` / `py:<name>`; R workers are heavy), and in slurm mode an
  allocation keeps occupying queue resources until session death or server
  death.

The agent therefore has no way to express "this task is over, release the
worker" — it either leaks the process or abuses `restart` semantics.

## 2. Design decision: explicit `close` tool, not TTL

Two candidate remedies, one chosen:

1. **`close(session)` tool (chosen).** Explicit teardown under the agent's
   control, paired with a SKILL.md discipline ("用完即弃" — close when the task
   is done). Fits the existing "explicit tools + skill discipline" model
   (`restart` already exists; `close` is `restart` minus respawn). Zero risk of
   surprising the agent mid-analysis.
2. **Idle TTL (rejected).** Auto-kill after inactivity. Conflicts with the
   skill's core promise that state survives across calls, compaction, and the
   agent's own thinking pauses (an agent deliberating for minutes must not lose
   the session). Also needs a last-activity clock per session — machinery for a
   case the agent can already handle explicitly.

## 3. Tool semantics

`close(session: str) -> Ack` — kill the named session's worker and evict it
from the pool.

- **Never spawns.** Unlike every other tool, `close` must not auto-create: a
  name that was never used (or whose worker already died) is a no-op success —
  `Ack(ok=True, message="no running session 'r:foo'")`. Idempotent, matching
  `restart`'s forgiving behavior.
- **Prefix rule applies.** Unprefixed/unknown-prefix names → the standard
  structured ambiguity error (same `_AMBIG` string, `Ack(ok=False,
  message=...)`), never a raised exception.
- **Slurm-aware.** If the session has a `job_id`, `scancel` it — the
  allocation is released, same as `restart`.
- **Lifecycle closure.** After `close`, `session_info` reports
  `running=False`; the next `run_code` on the same name goes through `_get`'s
  existing poll-detection path and spawns a fresh worker (empty namespace).
  Closing is therefore safe to undo — the cost is losing state, exactly as
  documented.
- **No effect on other sessions.** Only the named pool entry is touched.

## 4. Implementation

- Extract the kill sequence from `restart` (repl_server.py:466-493) into a
  shared `_kill(s: _Session) -> bool` helper (scancel → close conn/stdin →
  `terminate()` + `wait(2)`, each step guarded; returns whether a live worker
  was killed). `restart` = `_parse_session` → pop → `_kill` → respawn-on-next-
  use (unchanged behavior). `close` = `_parse_session` → pop → `_kill` → Ack.
- `restart`'s message stays "restarted session 'r:foo'"; `close` reports
  "closed session 'r:foo'" when a worker was killed, "no running session
  'r:foo'" otherwise.
- Tool registration alongside the other 7 tools; generic docstring in the
  established style.

## 5. SKILL.md discipline (agent behavior)

- Tools list gains the 9th entry with an explicit "sessions are **not**
  auto-closed" note.
- New short guidance in the restart section, distinguishing the two:
  `restart` = reset state, keep working; `close` = task over, release process
  + queue resources (next `run_code` respawns fresh).
- Multi-session discipline gains: when a task finishes or you move to another
  project, `close` the session instead of leaving the worker running.

## 6. Docs

- `references/tools.md`: "eight tools" → "nine tools"; new `close(session) →
  Ack` section with JSON example, mirroring `restart`'s.
- README: no tool inventory there — no change.

## 7. Tests (TDD)

1. `close` kills and evicts: `run_code` → `close` → `session_info` shows
   `running=False`; pool no longer holds the session.
2. `close` then `run_code` is a fresh namespace (variable set before close is
   gone — same assertion shape as `test_restart_clears_state`).
3. Idempotent: `close` on a never-started name returns `ok=True`, no worker
   spawned (assert no `python_worker` process / session_info false).
4. Ambiguity: unprefixed name → `_AMBIG` in `message`, `ok=False`.
5. Slurm: `close` on an slurm session scancels the job id (mirrors
   `test_slurm_python_restart_scancels` using the fake shims).
6. Isolation: closing one session leaves a second session running.

## 8. Out of scope

- No TTL / auto-close of any kind.
- No behavior change to the other 7 tools.
- No worker-mode changes (existing sessions under slurm keep running until
  closed/restarted; `worker_mode` switch semantics unchanged).
- No persistent session registry across server restarts.
