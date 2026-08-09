# Design: compute-env-setup skill

Date: 2026-08-09
Status: Approved (user: Altair Wei)

## Context

The repo (`my-scientific-skills`) is a collection of Claude Code skills for
scientific computing, following the posit-dev/skills paradigm. It currently
lacks a skill for compute environment setup — standing up, recording, and
debugging the software stacks that scientific tools run in.

`external/science-skills/skills/compute-env-setup` (from `JimLiu/science-skills`,
a "Claude Science style" assistant repo) was studied as a source. Its structure
is excellent but it cannot be copied verbatim:

1. **Platform coupling** — it presupposes the Claude Science runtime
   (`compute_details`, `compute_provider` kernel, `submit_job --env`,
   `ENVS[]`/`ENV_TABLE`, byoc adapters, bridge runners). None of these tools
   exist in Claude Code.
2. **Repo discipline** — CLAUDE.md forbids copying external/ skills verbatim;
   write original skills instead.
3. **Reference file is not portable** — `references/envs_reference.md` is a
   catalog of Claude Science's own bundled envs, not methodology.
4. **Convention conflicts** — external package is ~10k tokens total (our
   SKILL.md budget is ≤5k tokens / 500 lines, description ≤100 tokens), and its
   description triggers reference nonexistent concepts.

## Goal

A tool-agnostic `compute-env-setup` skill that teaches Claude Code to:
- recognize which backend shape it is working on,
- describe an environment with one declarative spec,
- build/register/resolve that env per backend,
- validate with a three-level ladder,
- diagnose common env failures,
- record what exists in a **private, per-host ledger** (never in this repo).

## Scope

**In:** local conda/venv, Docker (local builds), direct SSH hosts, Slurm/PBS
clusters.

**Out:** container-via-bridge runners, managed-API providers (Modal, GCP,
RunPod), any reference to Claude Science or openclaw-science tools.

**Privacy constraint:** this repo is public. No real hostnames, usernames,
paths, or cluster details may appear anywhere in the repo. Real environment
records live in a private per-host ledger outside the repo
(`$SCIENTIFIC_ENVS_DIR` or `~/.config/scientific-envs/<host>.md`). The repo
documents the ledger *format*, never its contents.

## Design

### Placement & registration

```
computing-infrastructure/compute-env-setup/
├── SKILL.md                      # ~2,500-3,000 tokens, methodology
└── references/
    └── envs_reference.md         # ~1,500 tokens, original generic examples
```

- New category `computing-infrastructure/` (cross-cutting: serves both
  bioinformatics and data-science skills; fits no existing category).
- Register a new plugin `computing-infrastructure` in
  `.claude-plugin/marketplace.json`.
- Root `README.md`: add install line + category table row.

### SKILL.md anatomy

| Section | Content | Source |
|---|---|---|
| frontmatter | `name: compute-env-setup`; `description` ≤100 tokens, "Use when…" with concrete triggers (create conda env, install toolchain, slurm, docker image, rebuild env, diagnose env failure) | repo conventions |
| Overview | One declarative spec says what an env *is*; build/register/resolve per backend; **read the private ledger before building anything** | external §Overview, rewritten |
| Provider shapes | local conda/venv · Docker local build · direct SSH host · Slurm/PBS cluster. Per shape: what "build", "register", "resolve" mean. Slurm essentials: module load / apptainer, `--account/--partition/--time` often mandatory, compute nodes often lack egress | external §Provider shapes, minus bridge/byoc |
| Declarative spec | fields `base / system_pkgs / pip_phases / env / run_commands / shim_files / weight_dirs / smoke probes`; keep the "pip_phases ordering is the fix" insight; drop `ENVS[]/ENV_TABLE` runtime references | external §The declarative spec, rewritten |
| Validation ladder | import works → kernel-dispatch witness (seeded minimal task printing a sentinel) → sub-agent follows the doc verbatim; third level expensive, run after rebuild/doc edit and before declaring ready | external §Validation, kept |
| Diagnosis table | ~10 most universal rows: SM-version mismatch, numpy alias removal, `libfoo.so` loader path, force_reinstall snap-back, completion-marker files, RO-mount lockfile writes, `--config` overriding CLI, thread storm, job COMPLETED with empty output; mark container-only rows | external §Diagnosing, trimmed |
| Private ledger | `### env: <name>` block format (how / tier / weights / validated / gotcha); location `$SCIENTIFIC_ENVS_DIR` or default `~/.config/scientific-envs/<host>.md`, one file per host; read-before-write, append new blocks, replace stale lines | external §compute_details, adapted to a private file convention |
| Reference pointer | when to read references/envs_reference.md | — |

### references/envs_reference.md

Four original generic examples echoing the repo's own toolchains, each with
base / apt / pip_phases (with the *why*) / validation commands / gotchas:

1. `eda-cpu` — pandas/numpy/scikit-learn stack (echoes
   exploratory-data-analysis skill).
2. `popgen-cpu` — PLINK + ADMIXTURE (echoes population-genomics skill,
   conda-forge/bioconda).
3. `torch-gpu` — PyTorch cu12x stack; pip_phases ordering example + GPU
   witness command.
4. Slurm submission recipe — not an env but "how register/resolve works on
   this shape": module/apptainer + sbatch template.

All examples use placeholder host/version identifiers, no real hosts.

### Testing strategy (implementation phase)

Follow superpowers:writing-skills TDD for skills:

- **RED** — run 2-3 pressure scenarios with sub-agents *without* the skill
  (create an env and record it / deploy to a cluster / diagnose an
  ImportError); document baseline behavior verbatim. Scenarios use fictional
  hostnames; no real environments touched.
- **GREEN** — write the skill; re-run same scenarios; verify behavior change.
- **REFACTOR** — close loopholes found in testing; re-test.
- CLAUDE.md local loop: copy to `~/.claude/skills/`, try trigger / non-trigger
  prompts.
- `count-skill-tokens.py` to verify budgets (SKILL.md ≤5k tokens / 500 lines,
  description ≤100 tokens).
