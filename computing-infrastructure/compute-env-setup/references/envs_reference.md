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
