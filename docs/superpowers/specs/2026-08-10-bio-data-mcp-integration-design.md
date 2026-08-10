# bio-data MCP Integration — Design

**Date:** 2026-08-10
**Status:** Approved (brainstorming phase) → ready for implementation plan
**Approach:** B — self-authored single MCP server as its own `biomedical-data` plugin (cross-cutting data layer)

## Goal

Let skills in this marketplace depend on a curated set of public biomedical
data APIs (NCBI, ClinVar, dbSNP, GWAS Catalog, Open Targets, gnomAD, MyGene,
Ensembl) through **one** MCP server that ships with the new `biomedical-data`
plugin and requires **zero user setup** — no env provisioning, no path
configuration, no license entanglement from vendored third-party code. The
plugin is a **cross-cutting data layer**: both `bioinformatics` and
`scientific-writing` skills reference its tools, so neither domain plugin has
to pull the other just for data access.

## Non-goals

- Reproducing all 24 of Claude Science's `bio-tools` servers. Chemistry,
  drug-regulatory, cancer-models, clinical-trials, cellguide, etc. are out of
  scope — they don't serve the existing GWAS/popgen or writing skills.
- Vendoring, copying, or redistributing any `bio-tools` code, `schemas.json`,
  or fleet packages from `external/science-skills`. `external/` is studied as
  reference only (per `CLAUDE.md`); the implementation is clean-room against
  public API documentation.
- Retrofitting existing GWAS skills (`post-gwas-analyses`,
  `gwas-association-testing`, `population-genomics`) to actually call the new
  tools. That is Phase 2.
- Reproducing Claude Science's `operon.mcp()` / `search_skills({prefix:
  "mcp-"})` indirection layer. Standard Claude Code has no `operon` tool;
  MCP tools surface directly as `mcp__<server>__<tool>`.

## Background — why this design

### How Claude Science launches `bio-tools` (no setup problem)

Claude Science is a **product** that bundles its own runtime (`core/src/mcp/`,
not present in the `science-skills` asset repo). That runtime owns every layer
that would otherwise be a setup burden:

| Layer | Product owns | User-facing? |
|---|---|---|
| Registry | `bundledRegistry.ts` declares each `mcp_*` server's command/args/env | invisible |
| Deps | per-server `installPip` version pins | invisible |
| Env | `MCPPool` resolves `python` to a managed `operon-mcp` conda env | user never creates it |
| Path | `${MCP_SERVERS_DIR}` substituted to a product-bundled staged-assets path | user never clones |
| Lifecycle | connectors "attached, detached, or authorized while it runs" (`SYSTEM_PROMPT.md` L308) — on-demand, not all-at-startup | on-demand |
| Sync | `vendor-sync.py` keeps vendored code and registry pins in lockstep | product-team build concern |

So from an end user's seat, there is no setup — install Claude Science and the
servers are registered, env-provisioned, path-resolved, and lazily attached.

### Why we can't do that — and how we eliminate setup differently

We are not a product; we ship a Claude Code **plugin** in an
optionally-installable marketplace, running inside Claude Code's runtime. A
plugin's only lever is a static `mcpServers` block (command + args + env).
There is no `bundledRegistry.ts`, no `MCPPool`, no shared conda-env
provisioning, and path substitution is limited to `${CLAUDE_PLUGIN_ROOT}` /
`${CLAUDE_PLUGIN_DATA}`. The `installPip` pins live in the absent `core/` and
are unavailable to us.

We do not try to rebuild the product's layers. We pick a structure that
**never produces the setup burden** in the first place — each product-owned
lever maps to a zero-setup plugin-world substitute:

| Product lever | Our substitute | User setup? |
|---|---|---|
| `operon-mcp` conda env + `installPip` pins | `uv run` + `# /// script` inline deps (proven by the in-house `repl` server) | no |
| `${MCP_SERVERS_DIR}` → staged assets | `${CLAUDE_PLUGIN_ROOT}` (install dir) + `${CLAUDE_PLUGIN_DATA}` (cache) | no |
| `MCPPool` on-demand attach / pooling | **one** server — nothing to pool, no "24 at startup" problem | no |
| `vendor-sync.py` vendored code + pins | clean-room rewrite; nothing to vendor or sync | no |
| `installPip` pins | our own inline `# /// script` dep block (`httpx`, `pydantic`, `mcp`, ...) | no |

This is exactly why the design mirrors the `data-science/interactive-repl`
precedent: `repl` already proved that a plugin can ship a zero-setup MCP
server via `uv run` + inline deps + `${CLAUDE_PLUGIN_ROOT}`. We reuse the
proven pattern rather than inventing one. The one structural difference:
`repl` is 1:1 (one server, one consumer skill, same plugin), where
co-location is natural; `bio-data` is 1:many across multiple domain plugins,
which is exactly when a dedicated shared plugin fits better than co-location.

## Architecture

One stdio MCP server named `bio-data`, launched by `uv run` from the plugin
install path. The server ships under a new cross-cutting `biomedical-data`
plugin (not owned by either domain). Server code lives inside a thin skill's
`scripts/` directory (mirroring `interactive-repl/scripts/repl_server.py`).

```
biomedical-data/bio-data/
├── SKILL.md                  # tool catalog + setup + graceful degradation
├── scripts/
│   ├── server.py             # mcp stdio server; registers ~14 tools; # /// script deps
│   ├── _common.py            # HttpClient, rate_limiter, retry, UA/contact, cache
│   ├── apis/
│   │   ├── pubmed.py         # NCBI E-utilities (ESearch/EFetch/ELink) + Europe PMC fulltext
│   │   ├── clinvar.py        # ClinVar VCV / accession
│   │   ├── dbsnp.py          # dbSNP rsID + region search
│   │   ├── gwas_catalog.py   # GWAS Catalog (EMBL-EBI REST)
│   │   ├── opentargets.py    # Open Targets (GraphQL)
│   │   ├── gnomad.py         # gnomAD public browser API (descriptive UA, rate-limited)
│   │   ├── mygene.py         # MyGene.info
│   │   └── ensembl.py        # Ensembl REST + BioMart
│   └── setup.sh              # idempotent (uv presence check + optional NCBI key prompt)
└── references/
    ├── tools.md              # full per-tool API reference (read on demand)
    └── bio-tools-architecture.md   # design rationale: public-API patterns we adopted
```

### Plugin registration

A **new** plugin entry in `.claude-plugin/marketplace.json`. The
`bioinformatics` and `scientific-writing` plugins are unchanged — neither
hosts this server; their skills reference the tools cross-plugin.

```jsonc
{
  "name": "biomedical-data",
  "description": "Cross-cutting public biomedical data MCP layer — NCBI, ClinVar, dbSNP, GWAS Catalog, Open Targets, gnomAD, MyGene, Ensembl. Consumed by bioinformatics and scientific-writing skills.",
  "source": "./",
  "strict": false,
  "skills": ["./biomedical-data/bio-data"],
  "mcpServers": {
    "bio-data": {
      "command": "uv",
      "args": ["run", "${CLAUDE_PLUGIN_ROOT}/biomedical-data/bio-data/scripts/server.py"]
    }
  }
}
```

The root `README.md` gains a new `biomedical-data` row in the category table
and a matching install line.

## Component design

### `server.py`
- `# /// script` inline dependency metadata: `mcp`, `httpx`, `pydantic`.
  Retry/backoff is hand-rolled in `_common` (no extra dep) — keeps the inline
  dep set minimal, matching the `repl` server's lean style.
- Creates one `MCPServer("bio-data")`, registers each tool with a schema
  authored from the public API's docs, dispatches to `apis/<x>.py`.
- Reads config from environment (`NCBI_API_KEY`, `NCBI_CONTACT_EMAIL`,
  cache dir from `CLAUDE_PLUGIN_DATA`).
- stdio entry; single long-lived process per session.

### `_common.py`
The shared layer — mirrors the *role* of `bio-tools`' `mcp_servers_common`
without copying it:
- `HttpClient` — shared `httpx` client with per-API base URL, UA, and
  contact-email header injection.
- `rate_limiter` — token-bucket per API matching each provider's policy
  (NCBI: 3 req/s without key, 10 req/s with `NCBI_API_KEY`).
- `retry` — exponential backoff on 429 / 5xx / transient network errors,
  capped so a single call cannot hang past the MCP transport budget
  (bio-tools measured ~60s; we adopt the same ceiling).
- `cache` — optional on-disk cache under `${CLAUDE_PLUGIN_DATA}/cache/`
  for expensive calls (PMC full-text, gnomAD frequencies), TTL per API.
- error marshaling — surface clean JSON errors to Claude, never a silent hang.

### `apis/*.py`
One module per API family. Each exposes plain functions taking a typed
`dict`/pydantic model and returning JSON-serializable results. Schemas are
defined from the public API documentation — not copied from `bio-tools`'
`schemas.json` (which was "captured from the original hosted connector").

## Tool catalog (Phase 1)

14 tools across 7 API families. Names are final for Phase 1; additional tools
are Phase 2.

| Family | Tool | What it does |
|---|---|---|
| PubMed | `search_pubmed` | ESearch — query PubMed, return PMIDs + count |
| PubMed | `fetch_pubmed` | EFetch/ESummary — abstract + metadata for PMIDs |
| PubMed | `find_related_articles` | ELink — related articles for a PMID |
| PubMed | `fetch_pmc_fulltext` | Europe PMC — full text for PMC IDs |
| Variants | `fetch_clinvar_variant` | ClinVar VCV/accession — clinical interpretation |
| Variants | `search_dbsnp_region` | dbSNP — rsIDs in a genomic region (GRCh38/GRCh37) |
| Variants | `dbsnp_get_rsids` | dbSNP — full records for a batch of rsIDs |
| GWAS Catalog | `search_gwas_catalog` | EBI REST — associations by trait / gene / region |
| Open Targets | `search_targets` | GraphQL — search targets by symbol |
| Open Targets | `target_associations` | GraphQL — genetic evidence for a target |
| gnomAD | `gnomad_variant_frequency` | public browser API — allele frequency (descriptive UA, rate-limited) |
| Genes | `query_genes` | MyGene.info — gene info by symbol / Ensembl ID |
| Ensembl | `query_ensembl` | Ensembl REST — lookup gene / region / variant |
| Ensembl | `query_biomart` | BioMart — bulk attribute query (e.g. gene list → attributes) |

## Data flow

Claude calls `mcp__bio-data__<tool>` directly (standard Claude Code; no
`operon.mcp()` indirection) → `server.py` dispatches to `apis/<x>.py` →
`_common.HttpClient` applies rate-limit / retry / UA / contact-email, hits the
public API → result is marshaled to JSON and returned to Claude. Cached calls
short-circuit to `${CLAUDE_PLUGIN_DATA}/cache/`. Once the `biomedical-data`
plugin loads, the `mcp__bio-data__*` tools are global, so any skill in any
plugin (bioinformatics, scientific-writing, …) can call them — no per-plugin
server duplication. Results reach downstream Python/R work as normal tool
outputs (no `./handoff/*.json` dance — that was a Claude Science `operon`-kernel
quirk that does not apply here).

## Setup & error handling (mirrors `interactive-repl`)

The thin `bio-data` `SKILL.md` carries a "Setup — check, then fix" section:

1. **Tools present?** Probe one cheap tool (e.g. `query_genes`). If it
   answers, done. Missing → continue.
2. **Plugin loaded?** If `mcp__bio-data__*` tools are absent, the
   `biomedical-data` plugin's `mcpServers` didn't load — tell the user to
   ensure that plugin is installed and Claude Code allowed the server.
3. **Deps self-bootstrap** via `uv run` inline deps — no manual env. If `uv`
   is missing, `scripts/setup.sh` installs it (idempotent, like `repl`'s
   `setup.sh`).
4. **API keys / contact** — optional: `NCBI_API_KEY` raises the NCBI rate
   limit 3→10 req/s; `NCBI_CONTACT_EMAIL` satisfies NCBI/E-utilities
   identification policy. Both read from environment (settings.json `env`).
   Missing → degrade gracefully (lower rate, warn in the tool result).

Errors: 429 / 5xx / network → `_common` retry with backoff, capped below the
MCP transport ceiling; on final failure return a clean JSON error to Claude,
never a hang.

## Configuration

| Env var | Purpose | Required? |
|---|---|---|
| `NCBI_API_KEY` | NCBI E-utilities rate limit 3→10 req/s | optional |
| `NCBI_CONTACT_EMAIL` | NCBI identification policy | optional but recommended |
| `CLAUDE_PLUGIN_DATA` | cache dir; injected by plugin launcher | injected |

Keys are configured via the plugin's `env` (settings.json), the same pattern
`interactive-repl` uses for `INTERACTIVE_REPL_R_ENV` etc.

## License & attribution

- Our code: **MIT** (matches the rest of the repo).
- `bio-tools` code: **not copied, not vendored, not redistributed.** Studied
  under `external/` per `CLAUDE.md` (read-only reference). Pacing/retry
  *values* learned from it are cited as rationale in
  `references/bio-tools-architecture.md` (original prose about public-API
  patterns, not copied code or schemas).
- Public APIs we call are cited in skill metadata with their usage policies
  (NCBI E-utilities, EMBL-EBI, Ensembl, Open Targets, gnomAD, MyGene.info).

## Phasing

- **Phase 1 (this spec):** `bio-data` server with the 14 tools above + thin
  `bio-data` skill (catalog + setup + degradation) + `setup.sh` + reference
  docs, all under the new `biomedical-data` plugin. Register in
  `marketplace.json` and `README.md`. **No changes to existing GWAS skills.**
- **Phase 2 (out of scope, later spec):** retrofit `post-gwas-analyses` and
  `gwas-association-testing` (under the `bioinformatics` plugin) to call
  `mcp__bio-data__*` tools where they currently hand-roll or skip public-data
  lookups. Cross-plugin reference — works because the tools are global once
  `biomedical-data` loads.

## Testing

- **Boot test:** `uv run biomedical-data/bio-data/scripts/server.py` starts
  and enumerates tools (smoke test).
- **Per-API hit tests:** small live-call checks per `apis/*.py` against the
  real public APIs (manual, not CI — networked). Record fixtures where useful.
- **Skill triggering:** per `CLAUDE.md`, copy to `~/.claude/skills/`, start a
  fresh Claude Code session, try prompts that should and should not trigger
  the `bio-data` skill; iterate on the `description`.
- **Size check:** `./count-skill-tokens.py biomedical-data/bio-data` — keep
  `SKILL.md` under 500 lines / ~5k tokens, description under ~100 tokens.

## Decisions made

- **Distribution:** clean-room self-authored single server — not vendoring
  `bio-tools`, not referencing `external/`, not shipping a thin wrapper
  pointing users at science-skills. (Resolves the license + 24-process +
  portability concerns.)
- **Placement:** its own `biomedical-data` plugin (Approach B) — a
  cross-cutting data layer not owned by either domain. Both `bioinformatics`
  and `scientific-writing` skills reference `mcp__bio-data__*`. This reverses
  the earlier Approach A (under `bioinformatics`) for a principled reason:
  the data layer isn't intrinsically bioinformatics — literature tools
  aren't bioinformatics, variant tools aren't writing. A cross-cutting layer
  gets a cross-cutting home, and a writing-only user need not install
  `bioinformatics` (or vice versa) just for data tools. Category name
  `biomedical-data` (not `science-data`, which collides with the existing
  `data-science` plugin).
- **Scope:** 14 tools across 7 public-API families aligned to the existing
  GWAS/popgen skills. Chemistry/drug/clinical-trials servers deliberately
  excluded.
- **Coupling:** direct `mcp__bio-data__<tool>` calls + graceful degradation,
  not an `operon.mcp()`-style indirection.
- **Phasing:** ship server + thin skill first; retrofit existing skills in
  Phase 2.
