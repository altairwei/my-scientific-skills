# CLI reference — literature_review.py

Run as `uv run scripts/literature_review.py <subcommand> [flags]`.
Stdlib-only (urllib/json/re/time) — no deps, no API keys, no env-var
config. The polite-pool email is auto-read from `git config user.email`
(cached per process; anonymous fallback if git has no email).

## Common

- **stdout:** all subcommands print JSON to stdout (small payloads).
- **stderr:** errors + warnings (e.g. "no DOIs found to verify").
- **Network:** CrossRef, OpenAlex, doi.org. `litrev_get` retries once on
  HTTP 429 (2s sleep); returns `None` on any other error (no crash).

## verify-dois

```bash
uv run scripts/literature_review.py verify-dois DOI1 DOI2 ...
# or extract DOIs from a file / stdin:
uv run scripts/literature_review.py verify-dois --from-text review.md
cat review.md | uv run scripts/literature_review.py verify-dois --from-stdin
```

Stdout JSON `{doi: {ok, title?, year?, journal?, retracted?, registry?, error?}}`.
The **3-valued `ok`** is the load-bearing detail:

| `ok` | meaning | action |
|---|---|---|
| `true` | resolves (CrossRef hit, or doi.org 2xx/3xx for non-CrossRef) | safe to cite |
| `false` | doi.org 404 | **likely fabricated or typo'd** — don't emit; `crossref-lookup` the real one |
| `null` | network/transient/5xx | **do not flag as fabricated** — retry later |

`retracted` is `true`/`false` only on a CrossRef hit; `null` for
non-CrossRef registries or unverified lookups. Detected via CrossRef's
`update-to` field, `subtype: retraction`, or a `RETRACTED` title prefix.

**Dot-segment defense:** DOIs with `.`/`..`/empty path segments are
rejected up-front (`ok: false`, `error: "dot-segment in DOI"`) — a
server/CDN that dot-normalizes could otherwise make a fabricated DOI
appear to resolve.

## crossref-lookup

```bash
uv run scripts/literature_review.py crossref-lookup "Author Year Title"
```

Stdout JSON `{doi, title, year, score}` or `null`. Use when you have a
citation's details but not its DOI — the alternative to
pattern-completing one. Returns the top CrossRef bibliographic match.

## search-openalex

```bash
uv run scripts/literature_review.py search-openalex "QUERY" [--n 10] [--filters F]
```

Stdout JSON list `[{doi, title, year, cited_by, venue, oa_url}]`, sorted by
`cited_by_count` desc. `--filters` is an OpenAlex filter string, e.g.
`from_publication_date:2022-01-01` or `concepts.id:C2778407487`.

## expand-citations

```bash
uv run scripts/literature_review.py expand-citations DOI [--n-backward 50] [--n-forward 15]
```

Stdout JSON `{references: [...], cited_by: [...]}`. `references` = the
paper's own bibliography (backward — `filter=cited_by:<id>`), the path to
the seminal paper. `cited_by` = papers citing this one (forward —
`filter=cites:<id>`), the path to follow-ups. Each entry is `{doi, title,
year, cited_by}`. Three OpenAlex requests total; empty lists if the DOI is
unknown to OpenAlex or rate-limited.

## extract-dois

```bash
uv run scripts/literature_review.py extract-dois FILE
cat review.md | uv run scripts/literature_review.py extract-dois
```

Stdout JSON list of DOIs found in the text — HTML-decoded,
balanced-paren SICI, `</`-truncated, markdown/punct-stripped. Pipe into
`verify-dois --from-stdin` to verify every DOI in a draft:

```bash
uv run scripts/literature_review.py extract-dois review.md \
  | uv run scripts/literature_review.py verify-dois --from-stdin
```

## style-pass

```bash
uv run scripts/literature_review.py style-pass FILE
cat review.md | uv run scripts/literature_review.py style-pass
```

Stdout JSON `{ok, issues: [{code, note}]}`. **Deterministic regex, no
LLM** — drafts quote untrusted paper/web text, and a free-text fix hint
the agent applies would be an indirect-injection channel; the codes
(EMDASH/HONEST/PROCNOTE/PARENDOI/LONGHEAD/FLATSTRUCT) are the
load-bearing checks. Run once before saving; fix in a single editing
pass; don't loop until `ok` (it's a lint, not a gate).

## Polite-pool email

The CrossRef/OpenAlex "polite pool" mailto is read automatically from
`git config user.email` (cached per process via `lru_cache`, so a 50-DOI
verify forks git once). It goes in the request — the User-Agent
`mailto:` suffix (CrossRef) and the `&mailto=` query param (OpenAlex) —
identifying the caller for better rate limits. **Nothing is sent to the
user.** If git is unavailable or has no email configured, fetches run
anonymously (best-effort, never fails). CrossRef's 0.06s sleep between
requests + the 429-retry handle rate limits regardless.

## Error & exit behavior

- Bad args / missing input → stderr message, exit 2 (argparse) or 1.
- Network failures never crash a subcommand — `litrev_get`/`litrev_head`
  return `None`, surfaced in the JSON (`ok: null`, empty lists).
