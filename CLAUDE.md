# CLAUDE.md

This repository is a collection of Claude Skills for scientific computing and research workflows. Skills are markdown files (plus optional supporting resources) that teach Claude specialized workflows. There is no application code to build, compile, or deploy — the only utility is `count-skill-tokens.py` (see below).

## Repository structure

Each skill lives in its own directory under a topical category:

```
<category>/<skill-name>/
├── SKILL.md          # required
├── references/       # optional — markdown docs loaded into context on demand
├── scripts/          # optional — executable helper scripts
└── assets/           # optional — files used in output (templates, examples)
```

Current categories: `bioinformatics/`, `data-science/`, `scientific-writing/`. Add a new category directory when a skill does not fit any existing one.

Do **not** create a `README.md` inside individual skill directories — `SKILL.md` is the only entry point.

## SKILL.md conventions

Every skill requires YAML frontmatter at minimum:

```yaml
---
name: skill-name           # must match the directory name
description: What it does AND when to trigger it — this is the primary
  triggering mechanism, so include concrete contexts and user phrases.
---
```

Optional frontmatter fields: `compatibility` (required tools/dependencies), `metadata` (author, version), `license`.

The body is instructions written **for Claude, not for end users**:

- Write in imperative, step-by-step form ("First do X, then check Y").
- Explain *why* steps matter rather than relying on rigid MUSTs — Claude follows reasoned guidance better than rules.
- Keep `SKILL.md` under 500 lines / ~5,000 tokens. Move large reference material into `references/*.md` with clear pointers about when to read each file (progressive disclosure).
- Keep `description` under ~100 tokens and make it slightly "pushy" — name the tasks, file types, and phrases that should trigger the skill, even when the user doesn't name the skill explicitly.

## Registering a skill

After creating a skill directory, add it to the appropriate plugin in `.claude-plugin/marketplace.json`. A cross-category skill may be listed under multiple plugins. Each plugin needs a matching install line in the root `README.md`, and the category table in `README.md` should list the new skill with a one-line description.

## Scripts

- Start scripts with a proper shebang. Python scripts may use inline dependency metadata (`# /// script`) so they run with `uv run`.
- Scripts in `scripts/` should be deterministic helpers — if several skills reinvent the same helper, extract and share it.

## Checking skill size

Warns when `SKILL.md` exceeds 5,000 tokens / 500 lines and when the description exceeds 100 tokens:

```bash
./count-skill-tokens.py <skill-directory>     # e.g. data-science/exploratory-data-analysis
```

## Testing a skill locally

Copy the skill directory into `~/.claude/skills/` and start a new Claude Code session, then try prompts that should (and should not) trigger it. Iterate on the `description` until triggering is reliable.
