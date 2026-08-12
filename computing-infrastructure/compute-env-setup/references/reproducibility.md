---
name: environment-reproducibility
description: Read alongside compute-env-setup when deciding how reproducible an environment must be and which artifact to use. Triggers on "container vs conda", "reproducible env", "which layer", "OS drift", "glibc".
---

# How reproducible should the environment be?

Match the artifact to what actually differs between environments — be honest about each layer's scope.

| Layer | What it controls | Artifact | Git-tracked? |
|---|---|---|---|
| OS | glibc, dynamic linker, userspace, ABI | Dockerfile / Apptainer `.def` → `.sif` | yes (the `.def`) |
| Dependencies | package versions, channels | `environment.yml` + conda-lock | yes |
| Data | weights, databases | private ledger block | no — ledger is private |

## Decision rules

- **OS-level drift** (older glibc on compute nodes, missing system libs) is a container's promise, **not** conda's — conda locks the dependency graph, containers lock the whole userspace. Use containers when hosts differ at the OS layer; use conda/venv when they share an OS.
- **No root** (shared university hosts, many clusters) rules out Docker and often even `apptainer build` — conda is the only privilege-free layer. Build containers off-cluster and `pull` instead.
- **Iteration speed** matters: yaml rebuilds are seconds-to-minutes, image rebuilds minutes-to-hours. Develop in conda, freeze to a container only when the OS layer or deliverable demands it.
- **YAGNI**: a pure-Python toolchain (PLINK/ADMIXTURE, most bioconda stacks) has no system-level deps — a container is over-engineering. A GPU tool with CUDA kernels is a different story: the driver/SM is the host's, which no userspace artifact controls — which is exactly why the validation ladder exists.
- **ImportError → install, don't work around.** Never substitute a different library to dodge a missing one — install the missing package (often via `pip` in the env, or conda). Prefer reusing an existing domain env over creating a new one.

## Why bit-for-bit reproducibility is not conda's job

Conda's design goal is **dependency resolution + environment isolation**, not whole-userspace closure. A lock file pins the resolve on one platform, but glibc, the dynamic linker, and the kernel ABI are simply outside conda's reach. That is exactly what a container (Docker/Apptainer) closes. The two are not either/or — they are layers: a `environment.yml` commonly lives *inside* a Dockerfile's `%post`/`RUN` as the dependency recipe, while the container handles the OS layer. The practical boundary is the one in the table above.