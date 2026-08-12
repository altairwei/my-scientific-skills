---
name: compute-env-setup
description: Use when setting up or recording scientific compute environments — conda/venv, Docker, direct SSH hosts, Slurm/PBS clusters. Triggers on "create conda env", "install toolchain", "switch software source"/"换源", "pip timeout", "slurm", "module load", "rebuild env", "what's in <env>".
metadata:
  author: Altair Wei
  version: "1.0"
license: MIT
---

# Setting up scientific compute environments

## Overview

An environment is a software stack (specific package versions, often with load-bearing install ordering), possibly large model weights, and a resource shape. Different backends materialise these differently; the job is to keep one declarative description of *what* the environment is and treat *how it gets built and addressed on each backend* as something you figure out once per backend. Most setup failures are network timeouts to default package sources and install-ordering conflicts, not exotic backend problems.

**Before building anything:** read the private ledger (below) — the env, or a near-match you can extend, may already exist. That same ledger is where you record what you set up.

**How reproducible should the env be?** Match the artifact to what actually differs between environments (OS → container, dependencies → yaml+lock, data → ledger). Conda resolves the dependency graph; only a container closes the whole userspace. See `references/reproducibility.md` for the layer table and decision rules — read it before you reach for a container, and note the rule: **ImportError → install, don't work around**.

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

**Local conda/venv.** You have a shell on the machine. Two ways to build, chosen by how the env will be reused:

- **Project-level (yaml-first).** The portable artifact is a git-tracked `environment.yml` at the project root (echoes the reproducible-project layout of the bioinfo-project-organization skill). `channels:` (conda-forge before bioconda), `dependencies` for conda packages, a `pip:` sub-list for the rest. Rebuild on a new host: clone the repo → `chsrc set conda` + `chsrc set pip` → `conda env create -f environment.yml`. For bit-for-bit rebuilds, add a lock file (conda-lock or `pip freeze`); the yaml is the readable spec, the lock is the machine-readable one. Constraints: the yaml's `pip:` block is a *single* pip invocation — for load-bearing install ordering keep the ordered `pip_phases` instead (see below). The env name *is* the name — no aliasing layer.
- **Ad-hoc (spec-first).** Read the spec's `pip_phases` and run them in order after `conda create -n <name> python=<X>` (or `python -m venv`). Right for a quick personal env; promote to a yaml when the env matters.

Weights live in scratch or home; download once, point the tool's cache env var there. "Registering" = appending a ledger block (record the yaml's path if yaml-first). Lowest ceremony; right for a personal machine.

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
| conda "Could not solve for environment specs" | spec | Channel/pin conflict. Add `-c conda-forge -c bioconda` (forge first) or `channel_priority: strict`; raise the `python` bound; split the env |
| conda install hangs for 10+ min (solve) | spec | Defaults solver is slow with bioconda. Use `mamba`/`micromamba` as a drop-in |
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

Related, at the boundary of spec and reproducibility: a dependency list must be **complete** (every runtime dep declared, or a `--no-deps` skip silently loses one) and **ordered** (each phase its own pip call, so an already-satisfied pin isn't upgraded). Adding a dep to the yaml or a phase is how you make the env rebuildable — the install is the test of that list.

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
