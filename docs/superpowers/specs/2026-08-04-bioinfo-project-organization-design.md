# Design: `bioinfo-project-organization` Skill

Date: 2026-08-04
Status: Approved by user (structure + scope + placement + name + large-output policy)

## Goal

A portable, tool-agnostic skill that teaches Claude how to organize a
computational-biology / scientific-research project for reproducibility,
following Noble (2009), *A Quick Guide to Organizing a Computational Biology
Project* (PLoS Comput Biol). The skill captures the **project-organization
core** of that methodology — directory layout, per-experiment driver scripts,
a chronological lab notebook, and Git practices — and can both *advise* on
structure and *scaffold* a new project with standard templates.

The skill is environment-neutral: it uses only generic tools (shell, git,
plain files) and names no specific platform, runtime, or artifact-tracking
service. It loads on demand when a user starts or organizes a computational
project, rather than living as always-on prompt content.

## Source & positioning

Noble (2009) is the sole methodological source. The skill distills the paper's
project-organization guidance into imperative, tool-agnostic instructions. It
is a *methodology* skill (like a style guide) — not a distilled agent, not an
analysis pipeline.

Scope is deliberately the **project-organization core**: principles, directory
organization, experiment/driver-script rules, lab notebook, Git practices, and
large-output handling. Noble (2009) also covers broader software-engineering
practices (unit tests, modular/DRY code, code documentation, output logging
via `tee`) and adjacent reproducibility practices (seed fixing, environment
locking, containerization); these are **out of scope for v1** (see Out of
scope) to keep the skill focused and cleanly triggerable.

## Skill structure

```
bioinformatics/bioinfo-project-organization/
├── SKILL.md                      # ~120–150 lines, < 5000 tokens
└── assets/
    ├── lab-notebook.md            # template with one example entry
    ├── .gitignore                 # generic computational-project ignores
    ├── runall                     # driver-script skeleton
    ├── experiments/README.md      # what a single experiment dir contains
    └── artifacts/README.md        # provenance log for large outputs
```

No `references/` in v1 — the methodology fits comfortably in one SKILL.md
(< 150 lines). No `scripts/` — scaffolding is done by Claude with Bash + Write
guided by the skill; a scaffold script would only restate the skill's own
instructions.

### SKILL.md outline

- **Frontmatter**: `name: bioinfo-project-organization`; `description` (trigger,
  below) < 100 tokens, slightly pushy per repo convention; `metadata: {author:
  Altair Wei, version: "1.0"}`; `license: MIT`.
- **Decision branch (lead with this)**: new project → scaffold from `assets/`;
  existing project → diagnose current layout, fill gaps, never force-rearrange.
- **Core principles**: *Reproducibility by a Stranger* — someone unfamiliar,
  including your future self, must understand what you did and why from the
  project files alone; *Murphy's Law* — everything you do, you will probably
  redo, so organize so that repeating with new data or parameters is trivial.
- **Directory organization**: logical top, chronological bottom — root
  organized by *what* (data, code, manuscripts), experiments by *when*
  (`experiments/YYYY-MM-DD[-desc]/`); never date-named directories at the
  project root. Three reference patterns: script-driven
  (`data/ scripts/ experiments/ doc/`), notebook-driven
  (`data/ notebooks/ experiments/ doc/`), compiled
  (`data/ src/ bin/ build/ experiments/ doc/`). `data/` recommended but not
  mandatory.
- **Experiment rules**: each experiment in `experiments/YYYY-MM-DD[-desc]/`; one
  `runall` driver recording every command; restartable
  (`if [ ! -f output ]; then … fi`); never hand-edit intermediate files —
  automate the edit in the script; relative paths; comment generously.
- **Lab notebook**: `lab-notebook.md` at project root, chronological. After
  every experiment append a dated entry (`## YYYY-MM-DD`) recording what was
  done, why, what was observed, conclusions, next steps. Record failed
  experiments and *how you know they failed*. Link key outputs (paths, plots,
  tables).
- **Git**: tracks "how you computed" — scripts, notebooks, docs, config.
  Commit per logical unit of work; tag milestones (`git tag YYYY-MM-DD-desc`);
  `git status` before starting new work; `.gitignore` excludes large files and
  environment dirs; branch for risky modifications of verified scripts; commit
  messages (what) and lab-notebook (why) complement each other.
- **Large outputs**: Git for code/docs/config; large binaries (model weights,
  large result tables, intermediate bulk) go to an `artifacts/` directory at
  the project root. `.gitignore` ignores the binary *contents* of `artifacts/`
  but **keeps** `artifacts/README.md` tracked — that file logs each artifact's
  source and generating command, so provenance survives in git while bulk does
  not. Keeps the repo cloneable while preserving traceability.

### `description` (trigger)

> Use when the user is starting, setting up, or organizing a computational or
> scientific research project — creating a directory structure for a new
> analysis, planning reproducible experiments, setting up a lab notebook, or
> deciding how to organize code, data, and results. Triggers on "organize the
> project", "project structure", "set up a new project", "directory layout",
> "lab notebook", "make this reproducible", or "runall". Applies Noble (2009),
> *A Quick Guide to Organizing a Computational Biology Project*:
> logical-top/chronological-bottom layout, a `runall` driver per experiment, a
> chronological `lab-notebook.md`, Git tracking code and docs.

(~95–110 tokens; tighten to ≤ 100 when writing SKILL.md.)

### Assets

Each asset is a drop-in template Claude places when scaffolding a new project;
each carries a short header comment explaining its purpose and that it should
be adapted to the project.

- `lab-notebook.md` — titled template with one example dated entry showing the
  expected fields (what / why / observed / conclusion / next / failed-how).
- `.gitignore` — covers `__pycache__/`, `.venv/`, `envs/`, `*.h5`, `*.pdb`,
  large `results/`, the binary contents of `artifacts/` (but
  `!artifacts/README.md` so the provenance log stays tracked), OS cruft;
  commented so the user trims to fit.
- `runall` — shell skeleton: shebang, `set -euo pipefail`, a variable block for
  all paths/files, a restartable `if [ ! -f ... ]; then ... fi` block, and a
  comment template.
- `experiments/README.md` — one-paragraph note that each experiment dir holds
  its `runall` plus `results/`, and that reusable code lives at the top level,
  not buried here.
- `artifacts/README.md` — a small table template (artifact name | source |
  generated-by command | date | notes) for provenance.

## Data flow (typical session)

User says "set up a new computational project" / "organize this project" →
skill triggers → Claude checks whether the project is new or existing →
**new**: proposes a pattern (script / notebook / compiled) based on the work
type, scaffolds dirs + drops assets, `git init` + initial commit →
**existing**: reads current layout + `git status` + `lab-notebook.md`, reports
what's missing, fills gaps non-destructively. Subsequent experiments: Claude
follows the experiment rules (dated dir, `runall`, restartable, no hand edits),
appends lab-notebook entries, commits per logical unit.

## Error handling

- Existing project with a different convention → do not force-rearrange;
  surface the gap, propose minimal additions (e.g., add `experiments/` +
  `lab-notebook.md`), let the user decide.
- No git initialized → propose `git init` + initial commit before scaffolding,
  so the first scaffold is itself a checkpoint.
- Large binary already committed to git → flag it, propose
  `git rm --cached` + move to `artifacts/` + `.gitignore`; do not rewrite
  history without consent.
- Ambiguous project type (script vs notebook) → ask the user; default to
  script-driven for general computational biology.

## Testing & registration

1. `./count-skill-tokens.py bioinformatics/bioinfo-project-organization` —
   SKILL.md < 5000 tokens / 500 lines, description < 100 tokens.
2. Local trigger test: copy to `~/.claude/skills/`, start a fresh session;
   positive prompts ("set up a new computational project", "organize my
   analysis directory", "make this reproducible") should trigger; negative
   prompts ("explain this function", "QC my reads") should not. Iterate on
   `description` until reliable.
3. Register under the `bioinformatics` plugin in
   `.claude-plugin/marketplace.json` (append
   `"./bioinformatics/bioinfo-project-organization"` to the plugin's `skills`
   array); add a row to the README.md `bioinformatics` category table.
4. No new plugin install line needed — the `bioinformatics` plugin is already
   installable.

## Out of scope (v1)

- The software-engineering practices from Noble (2009) beyond project
  organization: unit tests, modular/DRY code, code documentation, output
  logging via `tee`. (Belong in a separate software-engineering skill if added.)
- Adjacent reproducibility practices: seed fixing, environment/container
  locking. (Belong in a broader reproducible-research skill.)
- A scaffold helper script in `scripts/` — Claude scaffolds directly.
- `references/` — content fits one SKILL.md.
- Any mention of, or coupling to, a specific compute platform, runtime, or
  artifact-tracking service; the skill stays tool-agnostic.
