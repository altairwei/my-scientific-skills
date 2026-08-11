---
name: literature-review
description: Use when the task is a literature question — find the seminal paper
  for X, verify a citation or DOI, walk the citation graph, or synthesize the
  evidence across papers into a referee-grade review. Catches fabricated citations
  + retractions; lints the prose. Triggers on "literature review", "find the
  seminal paper for X", "verify these citations", "synthesize the evidence on X",
  "is this paper retracted". Skip for a single-paper lookup.
license: MIT
metadata:
  author: Altair Wei
  version: "0.1"
---

# Literature review

A literature question has two halves: finding the papers a domain expert would point to, and turning them into something more useful than a reading list — a synthesis that says what's established, what's contested, what's new, and where the holes are. Both halves can fail quietly and look like competent output until someone checks. The retrieval picks the citations; your recall picks the framing; the synthesis is the layer on top.

## Setup

1. **`uv` present?** If not, `curl -LsSf https://astral.sh/uv/install.sh | sh` and restart. The CLI is **stdlib-only** (urllib/json/re/time) — no deps to install, no env-var config, `uv run` just needs a python.
2. **Polite-pool email (auto):** the CrossRef/OpenAlex polite-pool mailto is read automatically from `git config user.email` — zero-config, cached per process, anonymous fallback if git has no email. (The email goes in the API request identifying you for better rate limits; nothing is sent to you.)
3. **bio-data MCP (optional):** if the `biomedical-data` plugin is installed, `mcp__bio-data__search_pubmed` / `fetch_pubmed` / `fetch_pmc_fulltext` give PubMed search + abstracts + PMC open-access full text. Probe once — if absent, OpenAlex/CrossRef still cover the scholarly index.

Run subcommands as `uv run scripts/literature_review.py <subcommand>`. Concrete recipes in `references/recipes.md`; full subcommand reference in `references/cli.md`.

## Which connector

Full-text + verification stack — pick the source that fits the field and the paper:

| when | use |
|---|---|
| abstract / title+authors+year | `mcp__bio-data__search_pubmed` / `fetch_pubmed`, or `literature_review.py search-openalex "QUERY"` |
| PMC open-access full text (biomedical) | `mcp__bio-data__fetch_pmc_fulltext` |
| web-accessible full text | `WebFetch` |
| **paywalled / preprint / non-biomedical PDF** | **the `pdf-explore` skill** — `pdf_explore.py text --pages <section> --out sec.txt` → `Read`, or `render`+`crop` a figure |
| resolve a DOI you're certain of / catch fabrication | `literature_review.py verify-dois 10.xxxx/...` |
| free-text citation → DOI | `literature_review.py crossref-lookup "Author Year Title"` |
| citation-graph walk (backward seminal / forward follow-up) | `literature_review.py expand-citations DOI` |
| prose lint before saving | `literature_review.py style-pass draft.md` |

## Pair with pdf-explore for full-text PDFs

This skill works at the bibliographic-metadata level — DOIs, titles, citation graphs, abstracts. Synthesis often needs more: a specific number, a methods detail, a figure. For paywalled PDFs, preprints, scanned docs, or papers outside PMC, the only full-text source is the PDF. **When a key paper's full text is needed, use the `pdf-explore` skill** — `pdf_explore.py text --pages <methods+results> --out sec.txt` → `Read`, or `render --pages N --dpi 200` + `crop` for a figure. literature-review finds+verifies across papers; pdf-explore reads one PDF deeply.

## Read the request for what it's actually asking

"What's the paper for X" wants one or two specific citations; "what's the evidence on X" wants a synthesis; "compare A and B" wants a comparison, not two adjacent summaries; "where are the gaps" wants the gaps, with the survey as supporting material. A two-word lay query wants you to choose the scope a domain expert would default to and say so up front — "I'll take this as asking about human RCT evidence; the animal literature is separate." Ask a clarifier only when the answer would genuinely change what you do.

## Grounding: retrieve first, then write

For broad-survey, where-are-the-gaps, and compare-methods requests, the first move is a literature sweep — `literature_review.py search-openalex` / `crossref-lookup`, a PubMed query via `mcp__bio-data__search_pubmed`, `web_search`, or whichever domain connector fits the field — and the answer is built from what comes back. A real survey usually carries on the order of fifteen or more distinct primary-paper DOIs, because each claim is anchored to the paper that established it; a handful of review citations is a reading list, not a synthesis. When the question is after a *specific* paper — "the original," "the seminal," a named trial or method — find the highly-cited primary publication that the follow-ups all cite, not a review or news piece about it.

That applies even when you know the answer cold. Resolving the DOI for a paper you're certain of — the Transformer paper, a textbook constant, a landmark trial — is a one-second tool call (`verify-dois`), and it's the difference between a citation and a claim about a citation. Verification is something that happens in your tool trace, not a sentence in your reply. **A DOI you emit either resolves to a real paper that says what you claim, or it's a fabrication, and the difference is checkable in five seconds.** When you have author/year/journal but not the DOI, look it up via `crossref-lookup` rather than pattern-completing one; when even those details are hazy, that's a search query, not a citation. For recent developments, contested findings, or anything you "remember" from near or after your knowledge cutoff, retrieval isn't optional.

After the first sweep, take the two or three most relevant hits and walk one step in each direction on the citation graph (`expand-citations DOI`): pull their reference lists (backward) and their cited-by lists (forward), then fold anything new and on-topic into the set before you start writing. The seminal paper a field builds on surfaces in the backward step; the recent work that extends or contests your top hits surfaces in the forward step, and neither reliably appears in a keyword sweep alone.

## Retractions and the null result

Sensational papers are findable because they were sensational, and some were later retracted or failed to replicate. CrossRef's `update-to` field flags retractions — `verify-dois` surfaces `retracted:true` on a CrossRef hit; for any high-profile or surprising finding, a check takes seconds. The related trap is the question whose honest answer is "no such paper exists": when someone asks for "the paper showing X" and X fell apart or was never established, the right answer names the claim, says what happened to it, and points to what the actual evidence shows — not the closest-matching citation. `verify-dois` returning `ok:false` (doi.org 404) is the signal that a DOI doesn't resolve — likely fabricated or typo'd; `ok:null` means unverified (network), not fabricated — don't flag it.

## Synthesis is comparison, not summary

A list of papers with one-sentence summaries is a bibliography. The useful layer is on top: this finding replicated, that one didn't; these three agree on the effect but disagree on mechanism; this approach wins in setting A and that one in B; this 2015 result was superseded by this 2022 one. Organize by theme or question, not by paper. For compare-methods requests the deliverable is the trade-off and a recommendation, not two summaries.

## Making the prose carry its weight

A review paragraph earns its place by opening on *your* synthetic claim and then spending citations to back it, not by opening on a citation and reporting what it found. "Chen 2019 reported a 40% reduction; Park 2020 reported 35%" is two index cards. "The effect is real but modest, with pooled estimates clustering at 35-40% (Chen 2019; Park 2020)" is a review. The diagnostic: read only the first sentence of each paragraph in sequence; if they form your argument, you've written a synthesis; if they form a list of author names, you've written an annotated bibliography in paragraph costume.

## Write prose, not a bulleted bibliography

The artifact should read like a section of a referee-grade review: paragraphs of connected argument, each making one claim and anchoring it with an inline citation, transitioning to the next. A page that is 80% bullet points is a reading list dressed up as a review — it tells the reader *that* papers exist, not what they collectively show. Reserve bullets for places a list is genuinely the right structure (a reference appendix, a head-to-head comparison table, an enumerated set of named methods); the synthesis itself is prose. If you find yourself starting consecutive lines with `- Author Year showed…`, that's a paragraph that hasn't been written yet.

## Calibrating to evidence

Say which findings are landmark and which are recent; flag preprints as preprints; note when older results were refined or overturned. Match confidence to evidence: a single-cohort finding is "one group reported X," a phase-3 RCT is stated plainly, a contested area gets both sides and an honest "unresolved." When the question contains a contested premise, engage the premise rather than building on it. When the request is about gaps, name specific ones and anchor each to what establishes it as a gap — "more research is needed" means you haven't found the actual hole.

## Put the answer in the answer — and open on the substance

The review — prose, citations, bottom line — belongs in your response text, where the reader sees it. For anything beyond a one-paper lookup, also save the full review as a markdown artifact (the `save_artifacts` tool) so the reader has a clean, linkable document; the chat reply *is* the answer, and the artifact link goes at the end of it, never as a "Report saved:" opener. A reply that is *only* "I've saved a 14-paper review, all DOIs verified" is not an answer — write the substance in the chat, then link the artifact.

The first sentence should be content the reader came for: the finding, the paper, the comparison. "Here's the synthesis," "All DOIs verified against CrossRef; no retraction flags," "I've verified every citation," "the report is current as of today" — these are process narration, and they don't belong in the chat reply *or* the saved artifact. Verification happens in your tool trace; the reader infers it from citations that resolve and claims that hold up. Do not write a "DOIs verified / no retractions" line anywhere in the output — not as an opener, not as a footer, not as an italic subtitle under the artifact title. The artifact body follows exactly the same rule as the chat reply: open on substance, close on substance. The register to aim for is a tight methods paragraph or a referee-grade mini-review: lead with the key result, lay out the supporting evidence with inline DOIs, address the obvious counterpoint or limitation, and close on what's still open. A reader who only gets your first paragraph should already have the answer.

Cite inline as a markdown link — `[Author Year](https://doi.org/10.xxxx/xxxxxx)` — so the rendered prose reads `(Author Year)` and the DOI rides in the href where a reader can click it and a regex can still extract it. If the DOI itself contains parentheses (some publishers use PII-style suffixes, e.g. `Sxxxx-xxxx(NN)nnnnn-n`), URL-encode them as `%28` and `%29` in the href so the markdown link does not break in simpler renderers. Do not use numbered `[1][2][3]` references (they desync the moment a paragraph is reordered), and reserve the raw `(DOI: 10.xxxx/...)` form for plain-text-only output; a sentence whose visible text is half identifier is not referee-grade prose. Section headings are short noun phrases (six words or fewer); when you have five or more topics, group them under two or three parent `##` headings and demote the rest to `###`. The goal is that a domain expert reading your review nods along, finds the papers they'd have named themselves, and doesn't catch you in a single claim you can't back.

## Style pass before saving

Before saving the artifact, run `uv run scripts/literature_review.py style-pass draft.md` once on the full markdown. Fix the issues it lists in a single editing pass, then save; do not call it a second time and do not loop until it returns ok. It is a lint, not a gate, and a clean draft on the first pass is normal. It is **deterministic regex, no LLM by design** — drafts quote untrusted paper/web text, and a free-text fix hint the agent is instructed to apply would be an indirect-injection channel; the codes (EMDASH/HONEST/PROCNOTE/PARENDOI/LONGHEAD/FLATSTRUCT) are the load-bearing checks.
