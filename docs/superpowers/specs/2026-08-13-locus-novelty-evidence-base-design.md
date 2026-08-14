# locus-novelty: evidence-base level (third level)

> **Status:** Design approved 2026-08-13. Refines the shipped `bioinformatics/locus-novelty` skill.
> **Parent spec:** `docs/superpowers/specs/2026-08-12-locus-novelty-skill-design.md`

## Goal

Add a **third assessment level — evidence base** — to locus-novelty. Today the skill auto-scores two levels (SNP/signal via r²+EFO, locus via ±500 kb) and asks the agent to judge EFO phenotype matching. The agent's intelligence is better spent judging **which studies and articles support a known locus** — the evidence base — than re-judging an EFO label the CLI already matched. So we add an evidence level whose verdict the agent assigns from a captured study list + abstracts.

## Key decisions (locked in brainstorming)

1. **Third level, not a replacement.** Evidence base joins SNP-level and locus-level. It does not remove EFO auto-matching (still the gate for levels 1 & 2); it adds a level.
2. **Agent-only verdict — no rigid auto-score.** The CLI captures the raw material (study provenance + abstracts + objective descriptors); the **agent** assigns the evidence verdict. Rigid thresholds on "evidence strength" mislead (two same-biobank studies aren't independent; large N / single ancestry raises generalizability doubt; an old unreplicated signal is stale). Levels 1 & 2 stay auto-scored (mechanical); level 3 is agent-judged (qualitative).
3. **Metadata + PubMed abstracts.** The CLI fetches each supporting study's metadata (one GET) *and* its PubMed abstract (efetch XML). Abstracts let the agent read effect direction, cross-cohort replication, and qualitative findings — the actual intellectual work.

## Grounded live API shapes (verified 2026-08-13)

- **GWAS Catalog study resource** — `GET /associations/{id}/study` returns the study object directly (top-level, **not** wrapped in `_embedded.studies`). Fields: `accessionId` (GCST…), `publicationInfo.pubmedId` / `.title` / `.publication` (journal) / `.publicationDate` / `.author.fullname`, `initialSampleSize`, `replicationSampleSize`, `ancestries[]` (`{type: initial|replication, numberOfIndividuals, ancestralGroups[].ancestralGroup, countryOfRecruitment[].countryName}`), `diseaseTrait.trait`. (The top-level `pubmedId` field is null; use `publicationInfo.pubmedId`.)
- **NCBI efetch** — `GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id=<csv>&retmode=xml` returns `PubmedArticle` elements with `.PMID` and `.Abstract/AbstractText[]` (structured chunks). Parseable with stdlib `xml.etree.ElementTree`. No API key required (3 req/s; 10 req/s with `NCBI_API_KEY`). `_common.HttpClient` already sends `NCBI_CONTACT_EMAIL`.

## Evidence-level verdict vocabulary (agent-assigned)

- `well_replicated` — multiple independent studies/cohorts, ideally across ancestries, adequate N, consistent direction.
- `single_study` — only one study reports it.
- `limited_evidence` — few/small studies, single ancestry, unreplicated, or inconsistent.
- `n/a` — locus is novel (no priors to assess).

Plus a one-line **reason citing the studies** (author, year, journal, N, ancestry). Applies only when the locus/signal is known (priors exist); a `novel_locus_and_signal` locus has evidence `n/a`.

## Components

### New: `apis/pubmed.py`

`abstracts(pmids: list[str]) -> dict[str, str]` — efetch db=pubmed, batch up to 200 PMIDs/call, retmode=xml, parse with `xml.etree.ElementTree` → `{pmid: abstract_text}` (join `AbstractText` chunks; empty string if absent). Uses `_common.HttpClient` (rate-limited, `NCBI_CONTACT_EMAIL` already wired). Stdlib only — no new dependency; the script's `# /// script` deps stay `["httpx"]`.

### Modify: `apis/gwas_catalog.py`

`_normalise(a, client)` gains one extra GET per association: `/associations/{id}/study`. Extracts the study fields above into a `study` dict added to the returned prior-report record. (One efoTraits GET + one study GET per unique association.)

### Modify: `locus_novelty.py run_pipeline`

After building `prior_reports` (now each carrying `study`), collect the locus's **unique non-null PMIDs** across priors, call `pubmed.abstracts(pmids)`, and attach each abstract to `prior_report.study.abstract` (studies without a PMID — unpublished catalog entries — get `abstract: null`, still counted as evidence). Compute `evidence_summary` via `score.evidence_descriptors(prior_reports)` (dedup studies by `accession` — always present — so the same study reporting multiple associations at the locus counts once). Leave `evidence_level: None` for the agent. Skip abstract fetch entirely for novel loci (no priors).

### Modify: `score.py`

Verdict logic (`snp_level_verdict`, `locus_level_verdict`, `combine`) **unchanged**. Add one pure helper:

`evidence_descriptors(prior_reports) -> {n_studies, n_ancestries, ancestry_set, max_n, year_range, has_replication}`

Objective summaries of raw facts — **not a verdict**. Computed from each prior's `study` field: `n_studies` = distinct `accession` (so one study reporting several associations at the locus counts once); `n_ancestries`/`ancestry_set` = distinct `ancestralGroup` across all studies' `ancestries`; `max_n` = max `numberOfIndividuals`; `year_range` = `[min, max]` publication year; `has_replication` = any study has a replication-stage ancestry entry. Pure function, no HTTP — testable offline.

### Modify: `report.py`

`build_candidates` adds two fields per candidate: `evidence_summary` (CLI-filled descriptors) and `evidence_level` (null, agent-filled). `agent_judgment` / `user_confirmed` remain. `write_outputs`: `candidates.json` carries the full prior_reports (with `study` + `abstract`) + `evidence_summary`; `draft_verdict.csv` gains an `evidence_level` column.

### Per-locus record shape

```
{trait, lead_snp, chr, pos_hg38, p, study_efo,
 prior_reports: [{catalog_lead, r2, efo_traits, efo_match_type,
                  study: {accession, pmid, title, author, journal, year,
                          n_initial, n_replication, ancestries, abstract}}],
 r2_threshold, locus_window,
 evidence_summary: {n_studies, n_ancestries, ancestry_set, max_n, year_range, has_replication},
 snp_level_auto, locus_level_auto, combined_auto,
 evidence_level: null,        # agent fills
 agent_judgment: null,        # agent fills — known/likely-known/novel + reason, evidence-grounded
 user_confirmed: null}
```

### Modify: `SKILL.md`

"Two-level rules" → **"Three-level rules"**, adding the evidence level and the agent-only asymmetry note. **Workflow step 4 reframes** from "Apply EFO judgment" to **"Apply evidence-base judgment (your job)"**: read `candidates.json`; for each known/likely-known locus review the supporting studies (PMID, author, year, N, ancestry, replication) and their abstracts; judge evidence strength; assign `evidence_level` + a reason citing the studies. Same "don't lightly declare novel" caution, now evidence-grounded. **Verdict table** gains: evidence level + the supporting-study list (author year journal, N, ancestry).

### Modify: `references/novelty-rules.md`

Add the evidence level, the asymmetric "no auto-score" rationale, and how it combines with snp+locus (evidence modulates only when locus/signal is known). `references/ld-sources.md` unchanged.

## Alternatives rejected

- **Rigid `evidence_level_auto` thresholds** (≥2 studies + replication + N → well_replicated, else single/limited). Conflicts with decision 2 (agent-only) and with the rigidity problem. The CLI computes only objective *descriptors*, never a verdict.
- **Lazy abstract fetch by the agent.** Breaks the reproducibility bundle (it must capture exactly what the agent reasoned over) and the locked "deterministic CLI, agent judges" constraint (locus-novelty spec decision (b)). The CLI fetches; the agent judges.
- **Routing through the bio-data MCP.** Violates locus-novelty's locked constraint (b): this skill is a deterministic CLI calling public APIs directly, not the bio-data MCP.

## Testing

- `test_pubmed.py` — MockTransport returns efetch XML fixture → `abstracts` returns `{pmid: joined_text}`.
- `test_score.py` — add `evidence_descriptors` cases (n_studies dedup by PMID; ancestry_set; max_n; year_range; has_replication).
- `test_gwas_catalog.py` — `_normalise` issues the `/associations/{id}/study` GET and the `study` field is populated.
- `test_report.py` — `build_candidates` includes `evidence_summary` + `evidence_level: None`; `draft_verdict.csv` has the `evidence_level` column.
- `test_cli_boot.py` — CLI still imports cleanly (new `apis.pubmed` import wired).

## Scope check

Single subsystem (locus-novelty), additive refinement. No new skill, no cross-cutting plugin change, no marketplace change. One new module + targeted edits to four existing files + two doc files. Fits one implementation plan.
