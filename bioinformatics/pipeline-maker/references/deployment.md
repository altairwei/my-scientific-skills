# Deployment

Loaded when the user asks about environments, cluster/cloud execution, or when a job OOMs. Distilled from `external/snakemake/docs/executing/cli.rst` + `snakefiles/{rules,best_practices}.rst` (rewritten).

## Conda envs

`workflow/envs/<tool>.yaml` (channels: `conda-forge`, `bioconda`; dependencies pinned). Per-rule `conda: "envs/<tool>.yaml"` directive; Snakemake auto-activates the env at job time. Enable with `--sdm conda` (or `software-deployment-method: [conda]` in a profile). Pin versions for reproducibility.

## Apptainer / containers

`container: "docker://img"` or `"oras://..."` per rule (or globally). Enable with `--sdm apptainer`. If the image lacks bash, set `resources: shell_exec="sh"` (Snakemake defaults to bash strict mode, which fails in a busybox-style image).

## Executor plugins (Snakemake 8+)

Execution is pluggable: `--executor local|slurm|kubernetes|...`. SLURM via `snakemake-executor-plugin-slurm`. Configuration boils down to choosing an executor (+ optional storage plugin, e.g., S3 for remote I/O). See the plugin catalog at `snakemake.github.io/snakemake-plugin-catalog`.

## Profiles

- **Global profile** (compute environment): `--profile <name>` or `$SNAKEMAKE_PROFILE`; lives in `profiles/<name>/profile.yaml` (or `~/.config/snakemake/...`, `/etc/xdg/snakemake/...`).
- **Workflow-specific profile**: `workflow/profiles/<name>/profile.yaml` or `--workflow-profile <name>`; auto-loads `profiles/default/` if present.

Keys: `executor`, `jobs`, `cores`, `default-resources`, `set-threads`, `set-resources`, `set-scatter`, `rerun-triggers`, `keep-going`, `software-deployment-method`. Precedence: **CLI > workflow-profile > global-profile**. Multiple `--profile` merge (later wins, at top-level key granularity).

## Profile is the authority layer

A profile's `set-resources: <rule>: mem_mb: N` **overrides both** the rule's `resources:` directive AND `config.yaml`. When changing a rule's memory, edit **both** `config.yaml` AND the profile's `set-resources`, then verify the actual `mem_mb`/`-Xmx` a job would get via a dry-run. (The WGS agent's `config.yaml`-only edit silently didn't apply — the profile pinned 8192, so 200 jobs OOM'd before the fix took effect.) A running orchestrator caches config at start, so resource edits need a restart to take effect.

## Resource sizing & scatter

`resources: mem_mb=`/`runtime=`; dynamic resources via `attempt`/`input.size_mb` callables — e.g., `mem_mb=lambda wc, attempt: attempt * 200` scales mem on each retry (pair with `--retries N`). **Some tools scale memory with `interval × samples + a fixed per-sample overhead`**, not just input size — `GenomicsDBImport`/`GenotypeGVCFs` OOM'd at 24 GB for whole-chromosome intervals over 529 samples. Fix: scatter over a **finer sub-interval set** (`set-scatter`, or a `create_genotype_intervals` localrule producing ~16 Mb pieces) AND bump `mem_mb` rather than retry. When the OOM `MaxRSS` is only ~1 GB over the cap (e.g., 25 GB vs 24 GB cap), 40 GB gives ample headroom. Don't retry blindly — measure the real peak first.

## `--tmp-dir` must be absolute

GATK `--tmp-dir .` resolves to cwd, which for a Snakemake job is the **project root** — so GATK/TileDB scatter `libgkl*`/`libtiled*`/`loader_*`/`tmp_read_*` temp files in the project root. Use an absolute scratch path (`--tmp-dir /scratch/$SLURM_JOB_ID`) or `resources: tmpdir=choose_tmp(["/scratch/nvme", "/scratch/$SLURM_JOB_ID"])` (the `choose_tmp` helper picks the first valid path).

## Track `profiles/` in git

Per-rule memory budget is essential for full runs — even if `profiles/` is gitignored by default, **track it** (the WGS user explicitly un-ignored it: "内存用量对于 pipeline 完整运行来说还是挺重要的"). Before committing, confirm the profile contains no secrets (keys/passwords); account names and partition names are fine to commit (they're in `CLAUDE.md` already).

## SLURM `squeue`/`sacct` polling

Belongs to `bioinfo-project-organization`'s `runall`, not here. Two gotchas if you do poll from a `runall`: `squeue -j <gone>` exits 0 with empty output — poll the **output**, not the exit code; and `sacct` state strings must be whitespace-trimmed before comparison.
