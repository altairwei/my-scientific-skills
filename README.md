# My Scientific Skills

A collection of [Claude Skills](https://docs.anthropic.com/en/docs/claude-code/skills) for scientific computing and research workflows. Skills extend Claude's capabilities with specialized knowledge and step-by-step workflows, and are automatically activated by Claude based on your task.

## Available skills

### bioinformatics

Skills for bioinformatics and computational biology workflows (population genomics, NGS, single-cell, sequence analysis, ...).

| Skill | Description |
|-------|-------------|
| [population-genomics](bioinformatics/population-genomics/) | Population-genomics analysis workflows — QC, LD pruning, kinship, PCA, ADMIXTURE, TreeMix, f-statistics, and fastsimcoal2 demographic inference from VCF/PLINK data |
| [bioinfo-project-organization](bioinformatics/bioinfo-project-organization/) | Organize a computational biology / scientific research project for reproducibility — Noble (2009) layout, per-experiment `runall`, a chronological `lab-notebook.md`, Git practices, and an `artifacts/` directory for large outputs |

### data-science

Skills for data analysis, statistics, and visualization.

| Skill | Description |
|-------|-------------|
| [exploratory-data-analysis](data-science/exploratory-data-analysis/) | Guides Claude through a structured exploratory data analysis of a tabular dataset |

### scientific-writing

Skills for scientific writing, literature work, and publishing workflows.

*No skills yet — contributions welcome.*

## Installation

### Claude Code (plugin marketplace)

```
/plugin marketplace add <your-github-user>/my-scientific-skills
/plugin install bioinformatics@my-scientific-skills
/plugin install data-science@my-scientific-skills
```

Each category directory is a plugin; install only the categories you need.

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

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). New skills must follow the conventions in [CLAUDE.md](CLAUDE.md) — that file also guides Claude when you ask it to help you author a skill. Anthropic's [`skill-creator`](https://github.com/anthropics/skills/tree/main/skill-creator) skill is a recommended helper.

## License

[MIT](LICENSE)
