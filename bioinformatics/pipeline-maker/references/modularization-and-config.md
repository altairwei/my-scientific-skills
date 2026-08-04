# Modularization and config

Loaded when structuring the workflow into modules and config. Distilled from `external/snakemake/docs/snakefiles/{rules,modularization,best_practices}.rst` (rewritten).

## Stage-per-file layout

One `workflow/rules/<stage>.smk` per pipeline stage (e.g., `alignment.smk`, `variant_calling.smk`, `quality_control.smk`). The main `workflow/Snakefile` (or root `Snakefile`) loads config and `include:`s the stage files. This keeps each stage's rules in a focused, readable file and lets you reason about one stage at a time. A `rule <stage>_all:` per stage acts as the optional stage target, invoked explicitly like the default target.

## `common.smk` for shared helpers

Shared rule-formatting helpers live in `workflow/rules/common.smk` (e.g., a `get_vqsr_resource_args`-style builder that pairs GATK `--resource:label,key=… <vcf>`, a `get_log_path(wildcards, rule_name)` resolver, derived path constants like `ALIGN_DIR`). **Pure analysis logic belongs in `scripts/*.py`, not `common.smk`** — `common.smk` is for rule *formatting* (string builders, path resolvers). Helpers must be **called**, not bare-referenced, in directives (`log: get_log_path(wildcards, "rule")`, not `log: get_log_path`). Include `common.smk` once from the main Snakefile (or each stage file).

## `config.yaml` + `configfile:`

`configfile: "config.yaml"` in the Snakefile; access via `config["key"]` or `config["section"]["key"]`. Put samples, paths, and tunable params here. **New samples are added in `config.yaml`, never by editing the Snakefile.** For multi-sample workflows, use a `config/samples.tsv` table (columns like `sample`, `fq1`, `fq2`) and read it via an input function or `lookup()` so a fastq basename maps to the right sample id.

## Modules (Snakemake 8+)

`module name: snakefile: "path/to/Snakefile"` then `use rule name.* from name as alias_*`. Prefer `include:` for simple in-repo stage files; use `module`/`use rule` to import external or reusable workflows. `snakedeploy deploy-workflow` templates a published workflow into a config-driven instance (copies profiles under `workflow/profiles/`).

## `pathvars` (Snakemake 9+)

`<results>`/`<logs>`/`<temp>`/etc. placeholders in input/output/log paths, configurable globally (top-level `pathvars:` or config) or per-rule/module. Defaults: `results`/`stats`/`reports`/`temp`/`resources`/`logs`/`benchmarks`. Useful for reusable modules whose output root should be caller-configurable.

## Target rules

`rule all:` (or any rule with `default_target: True`) is the default target; `expand()` the final outputs. Keep target rules at the top of the file. Optional stage targets (`alignment_all`, `variant_calling_all`) let the user run one stage explicitly.

## `localrules:`

Rules that must run on the orchestrator node (e.g., a `create_intervals` BED generator that writes a file shared by all samples, or a manifest generator) are declared via `localrules: create_intervals, make_manifest` at the top of the stage file. Without this, Snakemake may submit them to the cluster, which breaks shared-file assumptions.

## Shadow directories and checkpoints

- `shadow: "shallow"`|`"full"` — run the rule in a shadow (copy-on-write) directory; useful when a tool writes many side files you don't want to declare as outputs.
- `checkpoint`s — for when the set of outputs is unknown until a rule runs (e.g., a variant caller producing a variable number of per-contig VCFs); the downstream `input:` is a function that queries the checkpoint's output directory.
