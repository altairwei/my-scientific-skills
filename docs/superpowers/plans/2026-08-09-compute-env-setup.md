# compute-env-setup Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a tool-agnostic `compute-env-setup` skill in this repo (new `computing-infrastructure/` category) that teaches Claude Code to set up, validate, diagnose, and privately record scientific compute environments (conda/venv, Docker, direct SSH, Slurm/PBS), with mirror switching (chsrc) as a first-class first step.

**Architecture:** Follows superpowers:writing-skills TDD — RED (baseline pressure scenarios without the skill, document behavior) → GREEN (write skill) → REFACTOR (close loopholes, re-test). The skill itself is `SKILL.md` (methodology) + `references/envs_reference.md` (generic worked examples), adapted from `external/science-skills/skills/compute-env-setup` but rewritten tool-agnostically per `docs/superpowers/specs/2026-08-09-compute-env-setup-design.md`. Real environment records live in a private per-host ledger (`$SCIENTIFIC_ENVS_DIR` or `~/.config/scientific-envs/<host>.md`) — never in this public repo.

**Tech Stack:** Markdown skills, chsrc (referenced CLI), conda/pip/docker/sbatch workflows, `count-skill-tokens.py` for budget checks, Claude Code `Agent` tool for pressure scenarios.

**Spec:** `docs/superpowers/specs/2026-08-09-compute-env-setup-design.md` (commit `d1577c9`)

---

## File Structure

| File | Responsibility |
|---|---|
| `computing-infrastructure/compute-env-setup/SKILL.md` | **Create.** Methodology: mirror-first workflow, 4 provider shapes, declarative spec, validation ladder, diagnosis table, private ledger convention, reference pointer |
| `computing-infrastructure/compute-env-setup/references/envs_reference.md` | **Create.** 4 generic worked examples (eda-cpu, popgen-cpu, torch-gpu, Slurm submission) — original content, no real hosts |
| `.claude-plugin/marketplace.json` | **Modify.** New `computing-infrastructure` plugin entry |
| `README.md` | **Modify.** Category section + install line |
| `~/.claude/skills/compute-env-setup/` (outside repo) | **Create for testing.** Local copy used by GREEN scenarios and user sessions |

---

### Task 1: RED — baseline pressure scenarios (no skill)

Run 4 scenarios with the `Agent` tool (subagent type `general-purpose`), **before any skill exists**. Each scenario is a self-contained prompt (subagents have zero context). Record each subagent's choices and rationalizations **verbatim** in the session (these become the GREEN comparison baseline and feed the REFACTOR table).

- [ ] **Step 1: Scenario A — create & record (local)**

Run agent with prompt:
```
A researcher is starting a pandas/scikit-learn analysis project on this Linux
machine and asks you to set up the Python environment for it. Create a
dedicated environment, install pandas, scikit-learn, matplotlib, verify it
works, and leave a record that another person or agent could read later to
know exactly what was installed, how it was built, and how to rebuild it.
Report: what you did, what verification you ran, and what record you left
(and where).
```
Expected baseline to look for: ad-hoc install into the default env (or a new env with no recorded recipe); verification = `import` only or skipped; record = none or a loose README note; **no mirror check; no rebuild reproducibility**.

- [ ] **Step 2: Scenario B — pip timeout (network/mirror)**

Run agent with prompt:
```
You are helping a researcher install a scientific Python stack on a Linux
host. Every `pip install` fails with `ReadTimeoutError` — "Could not fetch
URL https://pypi.org/simple/...: Connection timed out" after ~30 seconds.
Fix the problem and complete the install of numpy, scipy, scikit-learn.
Report exactly what you did and why.
```
Expected baseline to look for: retry with `--timeout`/`--retries` flags; possibly a hand-typed `-i <mirror>` URL from memory; no systematic source management; may give up and tell the user to check the network.

- [ ] **Step 3: Scenario C — runtime failure after successful install (GPU)**

Run agent with prompt:
```
A tool was installed on a GPU host: `import torch` succeeds, but running a
model fails instantly with `RuntimeError: CUDA error: no kernel image is
available for execution on the device` on an A100. Diagnose and fix.
```
Expected baseline to look for: reinstall torch / suggest driver upgrade; **no SM-capability check** (`torch.cuda.get_device_capability()`), no wheel-vs-GPU matching, no `sm_range` record.

- [ ] **Step 4: Scenario D — Slurm deployment (cluster)**

Run agent with prompt:
```
Deploy a Python tool on a university Slurm cluster. The login node has a
module system; compute nodes have NO internet access. The tool needs several
pip packages. Write the deployment steps and the sbatch script.
```
Expected baseline to look for: sbatch script running `pip install` **inside the job** (fails — no egress); no `module load`/apptainer consideration; no pre-staging of packages/weights.

- [ ] **Step 5: Write up baseline**

In the session, collate the 4 subagent reports into a list of observed behaviors and verbatim rationalizations (e.g. "just retry with a longer timeout", "no one records envs for later"). This is the RED evidence; do not commit it to the repo.

---

### Task 2: Write `SKILL.md`

**Files:**
- Create: `computing-infrastructure/compute-env-setup/SKILL.md`

- [ ] **Step 1: Create the directory and write SKILL.md**

Run: `mkdir -p computing-infrastructure/compute-env-setup/references`

Write the full file below with the `Write` tool:

````markdown
---
name: compute-env-setup
description: Use when setting up or recording scientific compute environments — conda/venv, Docker, direct SSH hosts, Slurm/PBS clusters. Triggers: "create conda env", "install toolchain", "switch software source"/"换源", "pip timeout", "slurm", "module load", "rebuild env", "what's in <env>".
metadata:
  author: Altair Wei
  version: "1.0"
license: MIT
---

# Setting up scientific compute environments

## Overview

An environment is a software stack (specific package versions, often with load-bearing install ordering), possibly large model weights, and a resource shape. Different backends materialise these differently; the job is to keep one declarative description of *what* the environment is and treat *how it gets built and addressed on each backend* as something you figure out once per backend. Most setup failures are network timeouts to default package sources and install-ordering conflicts, not exotic backend problems.

**Before building anything:** read the private ledger (below) — the env, or a near-match you can extend, may already exist. That same ledger is where you record what you set up.

## Step 0 — Software sources (mirrors) first

On any host where downloads are slow or timing out, fix the source **before** installing. This is the most common cause of "software download/install timeout" — beginners get stuck here for weeks.

- Check the current source: `chsrc get pip`, `chsrc get conda`, `chsrc get ubuntu` (or `debian`).
- Switch with [chsrc](https://github.com/RubyMetric/chsrc) — a single binary that auto-tests mirrors and writes the right config. Install once: `curl https://chsrc.run/posix | bash`, then:
  - `chsrc set pip` — PyPI mirror (also covers poetry/pdm/uv via `chsrc set python`)
  - `chsrc set conda` — writes `~/.condarc`
  - `sudo chsrc set ubuntu` / `sudo chsrc set debian` — system apt repos, then `apt update`
  - `chsrc set docker` — Docker Hub registry mirror (relevant to the Docker shape)
- Pick the maintainer's fastest mirror with `chsrc set <target> first`, a specific one with `chsrc set <target> <mirror>`; view options with `chsrc list <target>`; speed-test with `chsrc measure <target>`; undo with `chsrc reset <target>`. Flags: `-dry` (preview), `-scope=project|user|system`.
- On a remote SSH host, install chsrc *on that host* and run it there — the local machine's sources don't transfer.
- chsrc has **no GitHub target**: for git-clone timeouts, use a manual rewrite like `git config --global url."https://<mirror-prefix>/".insteadOf "https://github.com/"`. Mirror availability varies — don't bake a specific prefix into a recipe.

## Provider shapes

Recognise which shape you're in — it determines what "build", "register", and "resolve" mean. Shapes blend at the edges; you're recognising, not choosing.

**Local conda/venv.** You have a shell on the machine. No image step: read the spec's `pip_phases` and run them in order after `conda create -n <name> python=<X>` (or `python -m venv`). The env name *is* the name — no aliasing layer. Weights live in scratch or home; download once, point the tool's cache env var there. "Registering" = appending a ledger block. Lowest ceremony; right for a personal machine.

**Docker (local build).** You build an image from a Dockerfile: `base` → `FROM`, `system_pkgs` → `apt-get`, `pip_phases` → ordered `RUN pip install`, `env` → `ENV`, `shim_files` → `COPY`, `run_commands` → `RUN`. A registry mirror (`chsrc set docker`) fixes pull timeouts. Register = tag (+ push to a registry); resolve = `docker run --gpus all ...`.

**Direct SSH host.** Same as local, but you are *on* the box via SSH: run the spec's phases in order there. Install chsrc on the host first. Weights: download once into scratch/home, set the tool's cache var. Register = ledger block for that host.

**Slurm/PBS cluster.** Shared filesystem, login node, compute nodes via `srun`/`sbatch`, usually no root. Software is `module load <name>` or Apptainer/Singularity containers in a shared path. For containers: `apptainer pull <name>.sif docker://<ref>` if the image was built elsewhere; `apptainer build --fakeroot` only if the cluster enables unprivileged user namespaces (many don't — build off-cluster and pull). Set `APPTAINER_CACHEDIR`/`APPTAINER_TMPDIR` to scratch first or the layer cache blows your home quota. For modules: write the modulefile under a *personal* tree (`$HOME/modulefiles/`) and `module use $HOME/modulefiles` in the job preamble. Weights go in shared scratch (usually purge-on-idle — record the purge window). Tier becomes scheduler directives: on most clusters `--account`, `--partition`, and `--time` are mandatory alongside `--gres=gpu:<type>:1 --cpus-per-task --mem`. **Compute nodes often have no internet** — mirrors are a login-node concern; pre-stage everything from the login node.

## The declarative spec

The portable artefact is a dict describing what the env *is*, independent of how any backend builds it. Every field maps to something each shape understands:

| Field | Meaning | Why it's portable |
|---|---|---|
| `base` | Starting image / interpreter+CUDA versions | `FROM`; on bare conda, read it as the python+CUDA versions to create |
| `system_pkgs` | OS-level packages | `apt-get` in a container; `conda install -c conda-forge` covers a subset on no-root hosts |
| `pip_phases` | **Ordered** `list[list[str]]` — each inner list is one `pip install` call | Every backend runs pip; ordering is the load-bearing part |
| `env` | Baked environment variables | `ENV`, `%environment`, or `conda env config vars set` |
| `run_commands` | Escape-hatch shell | `RUN`, `%post`, or just run it over SSH |
| `shim_files` | Small files to place in the env | `COPY`, `%files`, or `scp` |
| `weight_dirs` | `{name: {path, source, gated?, auth_hint?}}` | Declared once; *where* they live is provider-specific |
| smoke probes | `import_names`, `gpu_tests`, `cli_checks` | Run inside the env regardless of how it was built |

`pip_phases` ordering **is** the fix for every "package A drags B to the wrong version" problem — e.g. if a package pins a CPU-only torch wheel, install `["torch==2.3.1"]` as the phase **before** it: each phase is its own pip invocation, and pip leaves an already-satisfied requirement alone unless asked to upgrade.

When you find yourself adding a field only one backend understands, that field belongs in the per-host ledger, not the spec.

## Validation

Three levels; the gap between them is where the debugging time goes.

*Import works* — `python -c "import <pkg>"` returns 0. Necessary, cheap, catches almost nothing interesting.

*Dispatch witness* — a tiny seeded forward pass that prints a sentinel line with output shape, device name, and a non-emptiness check. Catches "torch sees the GPU but kernels were compiled for an older SM", "the `.so` isn't on the loader path", "inference writes to a read-only cache". Keep the witness in the ledger so the same probe runs on every backend.

*Agent follows the doc* — spawn a sub-agent per env, have it read the relevant tool docs and the ledger, run the documented invocation *verbatim*, and diff claim vs reality. This finds "doc says `--ligand` but the flag is `--ligand_description`". Routinely finds blocking bugs on envs whose import-level smokes have been green for weeks.

The witness is cheap — run it on every build. The agent-follows-doc pass is expensive — run it after any rebuild or doc edit, and before declaring the env ready.

## Diagnosing failures

When a documented invocation doesn't work, don't patch (add a flag, symlink a path, retry blindly). Ask which *layer* is wrong: network/mirror, spec, build, weights, resolution, or doc. Rows mentioning mount/entrypoint apply to container/apptainer shapes; the rest are universal.

| Symptom (grep-able) | Layer | What's actually wrong → fix |
|---|---|---|
| pip `ReadTimeoutError` / `Could not fetch URL ... connection broken` | network/mirror | Default PyPI unreachable. `chsrc set pip`, retry |
| conda `CondaHTTPError: HTTP 000 CONNECTION FAILED` | network/mirror | `chsrc set conda`, retry |
| apt `Failed to fetch ... Connection timed out` | network/mirror | `sudo chsrc set ubuntu` (or `debian`), `apt update`, retry |
| `no kernel image is available for execution` | build/spec | torch/jax compiled for older SM than this GPU. Record `sm_range` per env; rebuild only if no compatible hardware exists |
| `AttributeError: module 'numpy' has no attribute 'int'` | spec | Vendored dep predates numpy 1.24's alias removal. sed `np.int/float/bool/object` → builtins; don't delete the importing code (masks the symptom) |
| `ImportError: libfoo.so: cannot open shared object file` | build | Compiled-ops `.so` installed but not on the linker path. `find / -name 'libfoo.so'` → add its dir to `LD_LIBRARY_PATH` (often two libs: the ops `.so` + `libnvrtc.so.12`) |
| `ModuleNotFoundError` for a package not in your spec | spec | A `--no-deps` install skipped a runtime dep. Read the package's `pyproject.toml` `dependencies` and add them as an explicit phase |
| Wrong torch/numpy after install | spec | A later package's pin won the resolve. Add a `force_reinstall + no_deps` snap-back phase after it |
| Tool re-downloads despite populated weight dir | weights | `du -sh $CACHE_VAR` first. 0 B → populate step swallowed an error. Non-zero → tool checks a completion marker file, not the weights; bake that too |
| `OSError: Read-only file system` under `$CACHE_VAR` | weights (container) | Tool writes locks/`refs/` next to weights but the mount is RO. Symlink leaf blobs into writable `/tmp/<cache>`, export the var there |
| `--model_dir X` has no effect | doc/tool | Tool loads `--config <yaml>` *after* argparse and overwrites CLI flags. Patch the yaml at build time, or document "copy + edit the yaml" |
| 80-way thread storm on a 4-CPU tier | exec | `os.cpu_count()` returns the host's cores, not your allocation. Export `OMP/MKL/OPENBLAS_NUM_THREADS=<tier.cpus>` before exec |
| Job COMPLETED but output dir empty | exec | The wrapper that writes the phase marker never ran — often `#!/bin/bash` on a minimal runtime that only ships `/bin/sh` |

When you hit one of these, append symptom + fix to that host's ledger so the next agent doesn't rediscover it — when the symptom is a property of the provider, not of this project's data.

## The private ledger — recording what's set up

Per-host durable markdown. It documents what exists; it is **not** a resolution mechanism. The block is for the *next agent reading this host cold* — what env names exist, how each resolves on this host, what was validated when.

Location: `$SCIENTIFIC_ENVS_DIR` if set, else `~/.config/scientific-envs/<host>.md` — one file per host. **This directory is private: never commit it to a public repo.** If the ledger doesn't exist, create it; read before building; append new blocks; swap stale lines with a replace.

```
### env: <name>
how: conda env "<name>" on host                       # Slurm: apptainer $SCRATCH/images/<name>.sif
tier: {cpus: 8, mem_gib: 64, gpus: 1}                 # Slurm: partition, account, time, gres
weights: TOOL_CACHE_DIR=/scratch/weights/<tool> (12 GB; purge-window 30d)
sm_range: sm_80..sm_90
mirror: pip=<mirror> conda=<mirror> (switched <date>)
validated: <date> (dispatch-witness + agent-follows-doc clean)
gotcha: <any diagnosing-failures row hit on THIS host>
```

## Reference guides

- `references/envs_reference.md` — generic worked examples of the spec: base, pip_phases with the *why*, validation commands, gotchas. For any provider shape, this is the recipe — render the fields (to a Dockerfile, a shell session, an Apptainer def) or run by hand.
````

- [ ] **Step 2: Verify file**

Run: `head -5 computing-infrastructure/compute-env-setup/SKILL.md`
Expected: YAML frontmatter with `name: compute-env-setup` and the description.

- [ ] **Step 3: Commit**

```bash
git add computing-infrastructure/compute-env-setup/SKILL.md
git commit -m "feat(compute-env-setup): SKILL.md — mirror-first workflow, provider shapes, spec, validation, diagnosis, private ledger"
```

---

### Task 3: Write `references/envs_reference.md`

**Files:**
- Create: `computing-infrastructure/compute-env-setup/references/envs_reference.md`

- [ ] **Step 1: Write the reference file**

Write the full file below with the `Write` tool:

````markdown
---
name: compute-envs-reference
description: Generic worked examples of the compute-env-setup spec — read alongside compute-env-setup when building an env. Triggers on "which packages go in <env>", "pip order", "rebuild <env>".
---

# Compute environment reference — generic worked examples

Each entry is the build-spec that renders unchanged through any backend. All examples are generic (no real hosts); substitute versions freely. Every build starts with the mirror check (Step 0 in SKILL.md) before any install phase.

## eda-cpu — pandas/numpy/scikit-learn analysis stack

- **base:** `python:3.12-slim` / `conda create -n eda-cpu python=3.12`
- **mirror:** `chsrc set pip`; `chsrc set conda` if using conda
- **system_pkgs:** `libgomp1 build-essential` (only when the base lacks them; conda-forge wheels usually cover it)
- **pip_phases:**
  1. `numpy pandas scipy scikit-learn matplotlib seaborn polars` — one phase; keep the data-stack deps together so numpy/scipy resolve exactly once
- **validation:** `python -c "import pandas, sklearn, polars; print(pandas.DataFrame({'a': [1, 2]}).shape)"` → `(2, 1)`; a `RandomForestClassifier` fit on 200×5 rows → score round-trip
- **gotchas:** `polars` needs Python ≥3.11 for current wheels — don't pair it with an old base

## popgen-cpu — PLINK + ADMIXTURE toolchain

- **base:** conda env `popgen-cpu` (python 3.12)
- **mirror:** `chsrc set conda` — bioconda is heavy; the mirror matters more here
- **install:** `conda install -n popgen-cpu -c conda-forge -c bioconda plink admixture` — binary tools, no pip phase
- **validation:** `plink --version` → `PLINK v1.90b`; `admixture --help` → exits 0 with usage
- **gotchas:** bioconda can fight over the `python` pin — create the env with an explicit `python=3.12` to pin it; ADMIXTURE is single-threaded — scale by splitting chromosomes, not by adding cores

## torch-gpu — PyTorch CUDA stack with ordered pip phases

- **base:** `pytorch/pytorch:2.7.1-cuda12.8-cudnn9-devel` (devel: flash-attn compiles via nvcc) or `conda create -n torch-gpu python=3.11`
- **mirror:** `chsrc set pip`; `chsrc set conda`
- **system_pkgs (container):** `git build-essential ninja-build`
- **pip_phases (order is load-bearing):**
  1. `torch==2.7.1 --index-url https://download.pytorch.org/whl/cu128` — **torch first**, so nothing later drags a CPU-only wheel over it
  2. `flash-attn==2.8.0.post2 --no-build-isolation` — must see the base's torch headers; this pin ships prebuilt cu128 wheels (no 30-min nvcc compile)
  3. the tool's own deps (e.g. `transformers einops ...`) — installed *after* torch/flash-attn so their pins lose
- **env:** `CUDA_HOME=/usr/local/cuda`; `OMP_NUM_THREADS=8 MKL_NUM_THREADS=8` in the job preamble (tier cpus)
- **validation (dispatch witness):** seeded tensor round-trip printing a sentinel:
  `python -c "import torch; t = torch.randn(4, 4, device='cuda'); print('WITNESS', t.shape, t.device, bool((t @ t).numel()))"` → `WITNESS torch.Size([4, 4]) cuda:0 True`
- **gotchas:** `no kernel image is available` = wheel built for an older SM — check `torch.cuda.get_device_capability()` against the wheel's `sm_*` and record `sm_range` in the ledger; never install a torch-pinning package *before* phase 1 has run

## Slurm — submitting on a scheduler cluster

Not an env — how "register/resolve" works on this shape.

- **container path:** build the image off-cluster (or `apptainer pull <name>.sif docker://<ref>` on the login node); store under `$SCRATCH/images/`; set `APPTAINER_CACHEDIR=$SCRATCH/.apptainer APPTAINER_TMPDIR=$SCRATCH/.tmp` before pulling
- **module path:** `module use $HOME/modulefiles` in the job preamble; write modulefiles under `$HOME/modulefiles/`
- **sbatch template (directives often mandatory):**
  ```bash
  #!/bin/bash
  #SBATCH --job-name=<name>
  #SBATCH --account=<acct> --partition=<part> --time=01:00:00
  #SBATCH --gres=gpu:1 --cpus-per-task=8 --mem=64G
  module use $HOME/modulefiles && module load <name>
  export OMP_NUM_THREADS=8 MKL_NUM_THREADS=8
  srun <the documented invocation>
  ```
- **egress:** compute nodes usually have no internet — run `chsrc` on the login node; stage everything the job needs (weights, containers, wheels) *before* submit
- **gotchas:** scratch is often purge-on-idle — record the purge window in the ledger; run `sbatch --test-only` before a real submit if unsure the directives parse
````

- [ ] **Step 2: Verify file**

Run: `wc -l computing-infrastructure/compute-env-setup/references/envs_reference.md`
Expected: ~55 lines.

- [ ] **Step 3: Commit**

```bash
git add computing-infrastructure/compute-env-setup/references/envs_reference.md
git commit -m "feat(compute-env-setup): generic envs reference — eda/popgen/torch/Slurm worked examples"
```

---

### Task 4: Register the plugin

**Files:**
- Modify: `.claude-plugin/marketplace.json`
- Modify: `README.md`

- [ ] **Step 1: Add the plugin entry to marketplace.json**

In `.claude-plugin/marketplace.json`, append after the `scientific-writing` block (line 45 `}` of that plugin), before the closing `]`:

```json
    ,
    {
      "name": "computing-infrastructure",
      "description": "Skills for compute environment setup and infrastructure workflows",
      "source": "./",
      "strict": false,
      "skills": [
        "./computing-infrastructure/compute-env-setup"
      ]
    }
```

Then validate: Run `python3 -m json.tool .claude-plugin/marketplace.json > /dev/null` — Expected: exit 0, no output.

- [ ] **Step 2: Update README.md**

(a) After the `### data-science` section's `interactive-repl` table row, before `### scientific-writing`, insert:

```markdown
### computing-infrastructure

Skills for compute environment setup and infrastructure workflows.

| Skill | Description |
|-------|-------------|
| [compute-env-setup](computing-infrastructure/compute-env-setup/) | Set up and record scientific compute environments — conda/venv, Docker, direct SSH hosts, Slurm/PBS clusters; mirror switching first (chsrc), declarative env spec, three-level validation, private per-host ledger |
```

(b) In the Installation block, after `/plugin install data-science@my-scientific-skills`, add:

```
/plugin install computing-infrastructure@my-scientific-skills
```

- [ ] **Step 3: Commit**

```bash
git add .claude-plugin/marketplace.json README.md
git commit -m "feat(compute-env-setup): register computing-infrastructure plugin (marketplace + README)"
```

---

### Task 5: GREEN — re-run scenarios with the skill

**Files:**
- Create (outside repo): `~/.claude/skills/compute-env-setup/` (copy of the new skill)

- [ ] **Step 1: Install the skill locally**

Run:
```bash
mkdir -p ~/.claude/skills
cp -r computing-infrastructure/compute-env-setup ~/.claude/skills/
ls ~/.claude/skills/compute-env-setup/SKILL.md
```
Expected: the file exists.

- [ ] **Step 2: Re-run Scenario A (create & record) with skill**

Run agent with prompt (same task, skill-loaded):
```
A researcher is starting a pandas/scikit-learn analysis project on this Linux
machine and asks you to set up the Python environment for it. BEFORE doing
anything, read and follow the skill at
~/.claude/skills/compute-env-setup/SKILL.md. Create a dedicated environment,
install pandas, scikit-learn, matplotlib, verify it works, and leave a record
that another person or agent could read later. Report: what you did, what
verification you ran, and what record you left (and where).
```
Expected vs baseline: mirror check (`chsrc get/set pip`) appears; a ledger block is written under `~/.config/scientific-envs/` with env name, tier, mirror, validated fields; dispatch-witness-style validation beyond bare imports.

- [ ] **Step 3: Re-run Scenario B (pip timeout) with skill**

Run agent with prompt:
```
You are helping a researcher install a scientific Python stack on a Linux
host. Every `pip install` fails with `ReadTimeoutError` — "Could not fetch
URL https://pypi.org/simple/...: Connection timed out" after ~30 seconds.
BEFORE doing anything, read and follow the skill at
~/.claude/skills/compute-env-setup/SKILL.md. Fix the problem and complete
the install of numpy, scipy, scikit-learn. Report exactly what you did
and why.
```
Expected vs baseline: `chsrc set pip` (or explicit mirror switch) named as the fix, then retry; no blind `--timeout` patch.

- [ ] **Step 4: Re-run Scenario C (GPU runtime failure) with skill**

Run agent with prompt:
```
A tool was installed on a GPU host: `import torch` succeeds, but running a
model fails instantly with `RuntimeError: CUDA error: no kernel image is
available for execution on the device` on an A100. BEFORE doing anything,
read and follow the skill at
~/.claude/skills/compute-env-setup/SKILL.md. Diagnose and fix.
```
Expected vs baseline: diagnosis names the build/spec layer, checks `torch.cuda.get_device_capability()`, plans a `sm_range`-compatible wheel rebuild, records `sm_range` in the ledger.

- [ ] **Step 5: Re-run Scenario D (Slurm deployment) with skill**

Run agent with prompt:
```
Deploy a Python tool on a university Slurm cluster. The login node has a
module system; compute nodes have NO internet access. The tool needs several
pip packages. BEFORE doing anything, read and follow the skill at
~/.claude/skills/compute-env-setup/SKILL.md. Write the deployment steps and
the sbatch script.
```
Expected vs baseline: no `pip install` inside the sbatch script; module/apptainer preamble (`module use $HOME/modulefiles` or `apptainer pull` on login node); egress limitation acknowledged with staging steps; ledger block for the cluster.

- [ ] **Step 6: Compare and record**

Diff each GREEN report against the RED baseline. For any scenario where the skill failed to change behavior, note the rationalization the subagent used — those feed Task 6.

---

### Task 6: REFACTOR — close loopholes

- [ ] **Step 1: Analyze gaps**

For each scenario where GREEN did not match the expected behavior, quote the subagent's rationalization (verbatim) and identify which section of SKILL.md failed to prevent it (e.g. "the skill never said to check sources before install" or "ledger section didn't specify where").

- [ ] **Step 2: Patch SKILL.md**

Add an explicit counter to the relevant section for each rationalization (e.g. a sentence in Step 0: "Do not retry with `--timeout`; the timeout is the symptom, the source is the cause"; in the ledger section: "If no ledger file exists, create it before building — a build without a record is a rebuild you will regret"). Keep each patch a sentence or two; do not inflate the file.

- [ ] **Step 3: Re-run affected scenarios**

Re-run only the affected scenario(s) from Task 5 with the updated skill (`cp -r computing-infrastructure/compute-env-setup ~/.claude/skills/` first). Expected: behavior now matches.

- [ ] **Step 4: Commit**

```bash
git add computing-infrastructure/compute-env-setup/SKILL.md
git commit -m "feat(compute-env-setup): close loopholes found in GREEN testing"
```

---

### Task 7: Budget, consistency, and local trigger test

- [ ] **Step 1: Token budget check**

Run: `./count-skill-tokens.py computing-infrastructure/compute-env-setup`
Expected: no ⚠️ — SKILL.md ≤ 5,000 tokens / ≤ 500 lines; description ≤ 100 tokens; total reported without warnings.

- [ ] **Step 2: Spec coverage read-through**

Read `docs/superpowers/specs/2026-08-09-compute-env-setup-design.md` and check each row of its "SKILL.md anatomy" table exists in the final SKILL.md (Overview / Mirror switching / Provider shapes / Declarative spec / Validation / Diagnosis incl. 3 network rows / Private ledger / Reference pointer) and the 4 reference examples exist (eda-cpu, popgen-cpu, torch-gpu, Slurm). Fix any missing piece inline.

- [ ] **Step 3: Trigger test (user session)**

Copy is already at `~/.claude/skills/compute-env-setup`. In a **new** Claude Code session, try:
- Should trigger: "帮我建一个 conda 环境跑 pandas 分析" / "pip install 一直超时怎么办" / "帮我在 Slurm 上部署这个工具"
- Should NOT trigger: "写一段 pandas 代码" / "分析这个 VCF 的种群结构"
Adjust the `description` if triggering is unreliable.

- [ ] **Step 4: Final commit (if Task 6/7 changed files)**

```bash
git add -A computing-infrastructure/
git commit -m "feat(compute-env-setup): final budget/consistency fixes"   # only if files changed
```

---

## Self-Review

- **Spec coverage:** Overview ✓ (Task 2), Mirror switching first-class ✓ (Task 2 Step 0 + Task 6 patches), 4 provider shapes ✓, declarative spec + pip_phases insight ✓, validation ladder ✓, diagnosis table incl. 3 network rows ✓, private ledger format + location ✓ (repo contains format only, never real records), reference with 4 examples each starting from mirror check ✓ (Task 3), registry + README ✓ (Task 4), RED/GREEN/REFACTOR ✓ (Tasks 1/5/6), token budget ✓ (Task 7).
- **Privacy:** all examples generic; ledger path `~/.config/scientific-envs/` documented as private, never committed; scenario prompts use fictional hosts.
- **Tool-agnostic:** no reference to Claude Science, openclaw-science, or any product-specific tool surface.
- **Placeholder scan:** all steps contain full content (complete SKILL.md and reference file bodies included above); no TBD/TODO.
- **Consistency:** file paths and directory names (`computing-infrastructure/compute-env-setup`) match across all tasks; skill name in frontmatter matches directory name; `chsrc` command names (`set/get/list/measure/reset`, `-dry`, `-scope`) consistent between SKILL.md, reference, and diagnosis table.
