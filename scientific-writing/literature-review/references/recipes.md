# Recipes — literature-review

Concrete workflows. `LR` = `uv run scripts/literature_review.py`. The
retrieval picks the citations; your recall picks the framing; the
synthesis is the comparison layer on top.

## 1. Find the seminal paper for X

A keyword sweep surfaces recent popular hits, not the field's foundation.
After the sweep, walk one step backward on the citation graph:

```bash
LR search-openalex "X"                      # top hits by cited_by_count
LR expand-citations <top-hit-doi>           # references = the paper's bibliography
```

The most-cited entry in `references` (the backward step) is the seminal
paper the field builds on — it usually doesn't appear in a keyword sweep.
The forward step (`cited_by`) surfaces the recent work that extends or
contests your top hit.

## 2. Verify a citation / catch a fabrication

Before emitting any DOI, resolve it — a fabricated DOI looks identical to
a real one in the prose:

```bash
LR verify-dois 10.1038/nn.2300 10.1038/s41586-020-2649-2
# or from a draft:  LR verify-dois --from-text review.md
```

- `ok: true` — resolves (CrossRef hit, or doi.org 2xx/3xx for non-CrossRef
  registries like DataCite/arXiv/mEDRA).
- `ok: false` — doi.org returned 404; **likely fabricated or typo'd**.
  Don't emit it. Find the real one via `crossref-lookup`.
- `ok: null` — network/transient; **do not flag as fabricated** — retry
  later.
- `retracted: true` — CrossRef's `update-to` flags a retraction; surface
  it in the prose ("this finding was retracted in 2023").

When you have author/year/journal but not the DOI, **look it up, don't
pattern-complete one**:

```bash
LR crossref-lookup "Vasimuddin 2017 faster read mapping with minimap2"
```

## 3. Citation-graph walk (fold before writing)

After the first sweep, take the 2–3 most relevant hits and expand both
directions; fold anything new and on-topic into the set before writing:

```bash
for doi in <hit1> <hit2> <hit3>; do
  LR expand-citations "$doi"
done
```

The seminal paper surfaces in `references` (backward); the recent
follow-up / contest surfaces in `cited_by` (forward). Neither reliably
appears in a keyword sweep alone.

## 4. Synthesize from abstracts

For broad-survey / where-are-the-gaps requests, abstracts often carry
enough:

```bash
LR search-openalex "batch effect correction in scRNA-seq" --n 20
# then pull PubMed abstracts for the hits:
#   mcp__bio-data__search_pubmed → PMIDs → mcp__bio-data__fetch_pubmed
```

Read the abstracts, then write the synthesis — "these three agree on the
effect but disagree on mechanism," "this 2015 result was superseded by
this 2022 one." Organize by theme, not by paper. **Synthesis is
comparison, not summary** — a list of one-sentence-per-paper summaries is
a bibliography, not a review.

## 5. Synthesize from a PDF (pair with pdf-explore)

When the abstract doesn't carry the specific number / methods detail /
mechanism you need to synthesize, and the paper is a paywalled PDF /
preprint / outside PMC, read it with the `pdf-explore` skill:

```bash
# in pdf-explore:
uv run scientific-writing/pdf-explore/scripts/pdf_explore.py text paper.pdf \
  --pages 4,5,7-9 --out methods_results.txt
# → Read methods_results.txt, fold the specific numbers/mechanisms into the synthesis
# → verify the paper's own DOI via `LR verify-dois <doi>`
```

`pdf-explore` reads one PDF deeply (methods, results, figures);
`literature-review` finds + verifies across papers. Use both: find the
set with literature-review, read the key paper's details with pdf-explore.

## 6. Style pass before saving

Before saving the file, run the lint once on the full markdown:

```bash
LR style-pass review.md
# → {ok: false, issues: [{code, note}, ...]}
```

Fix every issue it lists in a **single editing pass**, then save. Do not
call it a second time, do not loop until `ok: true` — it's a lint, not a
gate; a clean draft on the first pass is normal. The codes:

| code | means |
|---|---|
| `EMDASH` | too many em-dashes (>8 per 1k words); replace most with comma/colon/period |
| `HONEST` | "honest answer/summary/read" framing; drop it, write the sentence it guarded |
| `PROCNOTE` | "DOIs were verified / no retractions / current as of" — process narration; delete |
| `PARENDOI` | a DOI href contains literal `( )`; URL-encode as `%28 %29` |
| `LONGHEAD` | 2+ `##` headings read as sentences; shorten to ≤6-word noun phrases |
| `FLATSTRUCT` | 7+ top-level `##`, no `###`; group under parents and demote |

The lint is **deterministic regex, no LLM by design** — drafts quote
untrusted paper/web text, and a free-text fix hint would be an
indirect-injection channel.
