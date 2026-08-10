# bio-data architecture rationale

This server is clean-room: no code, schemas, or fleet packages from Claude
Science's `external/science-skills/mcp-servers/bio-tools` were copied. That
repo was studied as reference only (per repo `CLAUDE.md`). The following
*patterns* (not code) were adopted because they reflect public-API etiquette,
not proprietary logic:

- **Per-API rate limiting.** NCBI E-utilities: 3 req/s without an API key,
  10 req/s with `NCBI_API_KEY` (NCBI's published policy). Other APIs get their
  own token bucket. Implemented in `_common.RateLimiter`.
- **Retry with exponential backoff on 429/5xx/transport errors**, capped under
  the ~60s MCP transport budget (the value bio-tools measured). Implemented in
  `_common.Retry`.
- **Contact-email + User-Agent identification.** NCBI asks clients to identify
  themselves; Ensembl's "polite pool" rewards a `User-Agent` containing a
  mailto. `HttpClient` injects these from `NCBI_CONTACT_EMAIL`.
- **On-disk cache** under `CLAUDE_PLUGIN_DATA` for expensive calls (PMC
  full text, gnomAD frequencies), per-API TTL.

## Why one server, not 24

Claude Science ships 24 separate `mcp_*` stdio servers (one per package), gated
behind a product runtime (`bundledRegistry.ts`, `MCPPool`, a managed conda
env) that hides all setup from the user. We are a plugin in an
optionally-installable marketplace — no such runtime — so 24 servers would
mean 24 processes per session and 24 `mcpServers` entries (scary + heavy). One
server with 14 curated tools keeps it to one process and a single
`mcpServers` line, while `uv run` + `# /// script` inline deps make it
zero-setup (mirrors the in-house `data-science/interactive-repl` server).

## Public APIs cited

NCBI E-utilities, Europe PMC, ClinVar (via E-utilities db=clinvar), dbSNP (via
db=snp), GWAS Catalog (EMBL-EBI REST), Open Targets Platform (GraphQL),
gnomAD (public GraphQL API), MyGene.info, Ensembl REST + BioMart. Usage
policies apply per provider; users set `NCBI_API_KEY` / `NCBI_CONTACT_EMAIL`
optionally.
