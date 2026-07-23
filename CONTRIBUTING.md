# Contributing

Contributions are welcome! A skill is a small, focused bundle of expertise: a `SKILL.md` file with instructions for Claude, plus optional `references/`, `scripts/`, and `assets/`.

## Adding a new skill

1. **Pick a category** (`bioinformatics/`, `data-science/`, `scientific-writing/`) or propose a new one.
2. **Create the skill directory** `<category>/<skill-name>/` with a `SKILL.md`. Follow the conventions in [CLAUDE.md](CLAUDE.md) — frontmatter with `name` and `description`, imperative step-by-step body, under 500 lines.
3. **Register it** in `.claude-plugin/marketplace.json` under the plugin matching your category.
4. **Document it** in the category table of the root `README.md` with a one-line description.
5. **Check its size**: `./count-skill-tokens.py <category>/<skill-name>` should show no warnings.
6. **Test it locally** by copying it into `~/.claude/skills/` and trying realistic prompts in a fresh Claude Code session.

The fastest way to draft a skill is to ask Claude to help — this repo's CLAUDE.md contains the full conventions, and Anthropic's `skill-creator` skill provides a guided create-test-iterate loop.

## Skill quality checklist

- [ ] `name` matches the directory name
- [ ] `description` says what the skill does *and* when to trigger it (under ~100 tokens)
- [ ] Body is written for Claude, imperative, and explains the *why* behind steps
- [ ] Large reference material lives in `references/`, not in `SKILL.md`
- [ ] No `README.md` inside the skill directory
- [ ] Registered in `marketplace.json` and listed in the root `README.md`

## License

By contributing, you agree that your contributions are licensed under the [MIT License](LICENSE).
