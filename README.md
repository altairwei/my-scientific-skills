# My Scientific Skills

A collection of [Claude Skills](https://docs.anthropic.com/en/docs/claude-code/skills) for scientific computing and research workflows. Skills extend Claude's capabilities with specialized knowledge and step-by-step workflows, and are automatically activated by Claude based on your task.

## Available skills

### bioinformatics

Skills for bioinformatics and computational biology workflows (population genomics, NGS, single-cell, sequence analysis, ...).

| Skill | Description |
|-------|-------------|
| [population-genomics](bioinformatics/population-genomics/) | Population-genomics analysis workflows — QC, LD pruning, kinship, PCA, ADMIXTURE, TreeMix, f-statistics, and fastsimcoal2 demographic inference from VCF/PLINK data |
| [gwas-association-testing](bioinformatics/gwas-association-testing/) | GWAS workflows — genotype QC, PCA stratification, phasing/imputation prep, and association testing with PLINK/REGENIE/SAIGE/LMM, including Firth regression, genomic control, and Manhattan/QQ/regional plots |
| [post-gwas-analyses](bioinformatics/post-gwas-analyses/) | Post-GWAS analyses of summary statistics — ANNOVAR/VEP annotation, heritability and genetic correlation (GCTA/LDSC), MAGMA gene tests, SuSiE fine-mapping, colocalization, meta-analysis, PRS, Mendelian randomization, TWAS, SMR/HEIDI |
| [bioinfo-project-organization](bioinformatics/bioinfo-project-organization/) | Organize a computational biology / scientific research project for reproducibility — Noble (2009) layout, per-experiment `runall`, a chronological `lab-notebook.md`, Git practices, and an `artifacts/` directory for large outputs |
| [pipeline-maker](bioinformatics/pipeline-maker/) | Build or recover a reproducible, modular Snakemake workflow from ad-hoc bash, a Jupyter notebook, or a described goal; mandatory `snakemake -n` dry-run loop, stale-code/force-stop/temp-cleanup recovery |

### data-science

Skills for data analysis, statistics, and visualization.

| Skill | Description |
|-------|-------------|
| [exploratory-data-analysis](data-science/exploratory-data-analysis/) | Guides Claude through a structured exploratory data analysis of a tabular dataset |
| [interactive-repl](data-science/interactive-repl/) | Persistent R/Python REPL via one MCP server (`repl`) with per-session language prefixes (`r:` / `py:`) — iterate in-session instead of re-running scripts; auto plot capture, variable inspection, sidecar injection; HPC/Slurm compute-node sessions |

### biomedical-data

Cross-cutting public biomedical data MCP layer — one server (`bio-data`) with 14 tools across NCBI E-utilities (PubMed), ClinVar, dbSNP, GWAS Catalog, Open Targets, gnomAD, MyGene, Ensembl/BioMart. Consumed by `bioinformatics` and `scientific-writing` skills; zero-setup via `uv run` inline deps.

| Skill | Description |
|-------|-------------|
| [bio-data](biomedical-data/bio-data/) | One MCP server exposing 14 public biomedical-data tools (PubMed search/fetch, ClinVar, dbSNP, GWAS Catalog, Open Targets, gnomAD, MyGene, Ensembl/BioMart); zero-setup via `uv run` inline deps; graceful degradation when the server isn't loaded |

### computing-infrastructure

Skills for compute environment setup and infrastructure workflows.

| Skill | Description |
|-------|-------------|
| [compute-env-setup](computing-infrastructure/compute-env-setup/) | Set up and record scientific compute environments — conda/venv, Docker, direct SSH hosts, Slurm/PBS clusters; mirror switching first (chsrc), declarative env spec, three-level validation, private per-host ledger |

### scientific-writing

Skills for scientific writing, literature work, and publishing workflows.

*No skills yet — contributions welcome.*

## Installation

### Claude Code (plugin marketplace)

```
/plugin marketplace add <your-github-user>/my-scientific-skills
/plugin install bioinformatics@my-scientific-skills
/plugin install data-science@my-scientific-skills
/plugin install biomedical-data@my-scientific-skills
/plugin install computing-infrastructure@my-scientific-skills
```

Each category directory is a plugin; install only the categories you need.

> **`biomedical-data` plugin also needs `uv`:** its `bio-data` MCP server launches via `uv run` (same mechanism as `repl` above). If `uv` isn't installed, see the steps under `data-science`.

> **`data-science` plugin prerequisite — `uv`:** the `interactive-repl` skill bundles one
> MCP server (`repl`) that launches via [`uv`](https://docs.astral.sh/uv/).
> `uv run` reads the server's inline `# /// script` metadata and installs the Python deps
> (`mcp`, `pydantic`, …) into an ephemeral env, so **once `uv` exists, no `pip install` is
> needed**. If `uv` isn't installed, add it first:
>
> ```bash
> curl -LsSf https://astral.sh/uv/install.sh | sh
> ```
>
> Then restart Claude Code so the MCP server picks up `uv` on `PATH`. (R sessions also need
> R installed — see `data-science/interactive-repl/references/r-setup.md`.)

### Manual

Clone this repository and copy the skill directories you want into `~/.claude/skills/`:

```bash
git clone https://github.com/<your-github-user>/my-scientific-skills.git
mkdir -p ~/.claude/skills
cp -r my-scientific-skills/data-science/exploratory-data-analysis ~/.claude/skills/
```

Once installed, Claude will automatically activate relevant skills based on your task.

## Repository layout

```
<category>/<skill-name>/
├── SKILL.md          # required — YAML frontmatter + instructions for Claude
├── references/       # optional — extra docs loaded on demand
├── scripts/          # optional — executable helper code
└── assets/           # optional — templates, example files
```

Skills are grouped into topical categories, each of which is a plugin registered in [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json).

The `interactive-repl` skill is the first to bundle MCP servers (declared inline via `mcpServers` on the `data-science` plugin entry, auto-started when that plugin is enabled). It is Claude-Code-specific; the other skills remain tool-agnostic and portable across agent platforms. Its workers can also run on Slurm compute nodes (srun + callback transport) for HPC centers.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). New skills must follow the conventions in [CLAUDE.md](CLAUDE.md) — that file also guides Claude when you ask it to help you author a skill. Anthropic's [`skill-creator`](https://github.com/anthropics/skills/tree/main/skill-creator) skill is a recommended helper.

## License

[MIT](LICENSE)
