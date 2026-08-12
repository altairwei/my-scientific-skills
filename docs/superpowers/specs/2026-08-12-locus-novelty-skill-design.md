# locus-novelty Skill — Design

**Date:** 2026-08-12
**Status:** Approved (brainstorming phase) → ready for implementation plan
**Approach:** A — deterministic CLI + candidate-JSON handoff; three-tier judgment (CLI scores → agent judges → user confirms)

## Goal

Give a GWAS practitioner a skill that, given a list of lead loci from a GWAS run, judges for each locus whether the association signal is **known or novel** at two levels:

1. **SNP level (signal level):** is the study's lead SNP in LD (r² ≥ threshold) with a previously-reported lead SNP whose phenotype is the same/similar? If not (r² < threshold against all same-phenotype cataloged leads), the signal is novel.
2. **Locus level:** within ±500 kb of the lead SNP, has any prior association with a same/similar phenotype been reported? If not, the locus is novel. Independent of LD — a novel signal can sit on a known locus.

The skill is a separate, self-contained skill under `bioinformatics/`, complementary to `post-gwas-analyses` (which routes "new signal vs known" to **GCTA-COJO** — a statistical, within-sumstats conditional method). This skill is the **literature-query** angle: it asks whether the signal has been *reported in public databases*.

## Non-goals

- Statistical conditional analysis (COJO) — already covered by `post-gwas-analyses`. This skill does not re-test sumstats; it queries public catalogs.
- Single-rsID deep-dive across 9 databases (GWAS Catalog + PheWAS + eQTL + …) — that's ClawBio `gwas-lookup`'s shape (reference, in `external/`). This skill is **batch novelty assessment** of a GWAS run's lead loci, not a per-rsID encyclopedia.
- Fine-mapping, colocalization, PRS — out of scope.
- Adding tools to `bio-data`. `bio-data` stays unchanged. The new skill is self-contained (own `_common`, own API clients, clean-room).
- Auto-declaring "novel" without a human in the loop. The agent judges semantics; the user confirms.

## Two-level judgment rules (precise)

### SNP level (signal level)

For each study lead SNP:
1. Resolve rsID → chr:pos (GRCh38), alleles, consequence (Ensembl `/variation/{rsid}` + VEP).
2. Pull prior associations from GWAS Catalog via the **SNP-exact endpoint** `GET /singleNucleotidePolymorphisms/{rsid}/associations` (the shape validated in the 2026-08-12 session analysis — free-text `associations?q=` is too loose for exact-SNP lookup).
3. Pull prior associations in the ±`--locus-window` (default 500 kb) region: `GET /associations?chromosome={chr}&start={pos-w}&end={pos+w}`.
4. Collect the **lead/index SNPs** of those prior associations (the cataloged lead SNPs at the locus).
5. Compute LD r² between the study lead SNP and each cataloged lead SNP:
   - max r² ≥ `--r2-threshold` (default 0.2) **and** the cataloged association's phenotype matches the study trait (same/similar per §EFO) → **SNP-level: known (same signal)**.
   - r² < threshold against all same-phenotype cataloged leads → **SNP-level: novel signal**.
   - r² ≥ threshold but phenotype **different** → flag `shared-signal-different-trait` (not novel; a separate category — the variant is known for a different trait).

### Locus level

Within ±`--locus-window` of the lead SNP, any prior association with a same/similar phenotype (per EFO matching) → **locus: known**. None → **novel locus**. Independent of the SNP-level LD result — a novel signal can still be on a known locus (different haplotype, same region).

## Architecture

```
bioinformatics/locus-novelty/
├── SKILL.md                    # teaches agent: determine LD source (ask if absent) → run CLI → read candidates.json → judge EFO → present verdict table → user confirms
├── scripts/
│   ├── locus_novelty.py        # entry CLI: --loci lead_loci.csv --output out/ --ancestry EUR [--ld-source plink|ldlink] [--ld-panel <bfile>] [--r2-threshold 0.2] [--locus-window 500000]
│   ├── _common.py              # HttpClient + RateLimiter + Retry + cache (clean-room, mirrors bio-data's _common patterns but independent)
│   ├── apis/
│   │   ├── ensembl.py          # resolve rsID → chr:pos/alleles/consequence (REST /variation + /vep)
│   │   ├── gwas_catalog.py     # SNP-exact + region associations + EFO traits
│   │   ├── ldlink.py           # LDproxy r² (window=500000, r2_d=r2) — NCBI, fallback when no local panel
│   │   └── ols.py              # EFO trait lookup + parent/child distance (Ontology Lookup Service)
│   ├── ld_plink.py             # PLINK --r2 wrapper (local reference panel, ancestry-matched)
│   └── report.py               # assemble candidates.json + draft_verdict.csv + reproducibility/
└── references/
    ├── novelty-rules.md        # the two-level rules + edge cases (shared-signal-different-trait, novel-signal-known-locus, etc.)
    └── ld-sources.md           # PLINK local vs LDlink trade-off + ancestry matching + the LDlink ldproxy call shape (cites GWASTutorial 19_ld)
```

### Marketplace registration

Add `./bioinformatics/locus-novelty` to the `bioinformatics` plugin's `skills` list in `.claude-plugin/marketplace.json`. Add a row to `README.md`'s category table. **No `mcpServers`** — this is a pure-script skill (no MCP server, unlike `bio-data`).

## Input / output

### Input (CLI)

```
locus_novelty.py \
  --loci lead_loci.csv \
  --output out/ \
  --ancestry EUR \
  [--ld-source plink|ldlink] \
  [--ld-panel <plink-bfile-prefix>] \
  [--r2-threshold 0.2] \
  [--locus-window 500000] \
  [--trait-efo-map trait_efo.csv]   # optional: pre-mapped trait→EFO (else CLI maps via OLS/GWAS Catalog)
```

- `lead_loci.csv` columns: `trait, chr, pos_hg38, lead_snp, p` (optional `gene_region, locus_type`).
- xlsx input is **not** parsed (YAGNI); if loci live in an xlsx (as in the 2026-08-12 reproductive-genetics session), extract to CSV first — SKILL.md notes this.
- `--ancestry`: EUR/AFR/AMR/EAS/SAS — selects the LDlink 1000G population and flags whether a local panel is ancestry-matched.

### Output (`out/`)

```
out/
├── candidates.json      # per-locus: prior-report candidates + auto score + EFO match evidence (CLI→agent handoff)
├── draft_verdict.csv    # per-locus one row, with blank agent_judgment + user_confirmed columns
├── report.md            # human-readable summary (filled by agent after judgment)
└── reproducibility/
    ├── commands.sh      # full CLI invocation
    ├── api_versions.json # per-API versions + query timestamps
    └── agent_judgment_log.md  # agent's per-locus judgment + one-line reasoning
```

`candidates.json` per-locus shape:
```json
{
  "trait": "PCOS", "lead_snp": "rs3945628", "chr": 9, "pos_hg38": 123773274, "p": 3.87554e-26,
  "study_efo": "Orphanet_4_282",
  "prior_reports": [
    {"source": "gwas_catalog", "catalog_lead": "rs3945628", "r2": 1.0, "efo_traits": ["Orphanet_4_282"], "efo_match_type": "exact", "auto_score": "known"}
  ],
  "snp_level_auto": "known",
  "locus_level_auto": "known",
  "agent_judgment": null,
  "user_confirmed": null
}
```

## LD switching logic (PLINK / LDlink + explicit consent)

- `--ld-source plink` (+ `--ld-panel <bfile>`) → PLINK `--r2`: gather the study lead + cataloged lead SNPs, compute r² locally. Accurate, ancestry-matched, offline.
- `--ld-source ldlink` → LDproxy API: `GET https://ldlink.nci.nih.gov/LDlinkRest/ldproxy?var={rsid}&pop={ancestry}&r2_d=r2&window=500000&genome_build=grch38&token={NCBI_API_KEY}` (call shape per GWASTutorial `19_ld`). 1000G fixed population — not strictly ancestry-matched.
- **If neither `--ld-source` nor `--ld-panel` is given, the CLI errors out** with a message pointing the user to the choice (it does not silently pick one). The **consent happens at the SKILL.md / agent layer before the CLI runs**: SKILL.md instructs the agent to ask the user first — *"No local LD panel given. Use LDlink (1000G `<ancestry>` population, not strictly matched)? Or provide a PLINK bfile prefix with `--ld-panel`?"* — then the agent invokes the CLI with the chosen `--ld-source`. No silent degradation to the less-accurate path. (More conservative than `bio-data`'s silent fallback.)
- `NCBI_API_KEY` is optional (raises LDlink rate limit 3→10 req/s). Since this is a pure-script skill (no `mcpServers`, so no plugin-launcher env injection), the key is read from the shell environment / `settings.json` `env`; setup checks for it and warns if missing.

## EFO matching flow (automated → agent judgment → user confirm)

### CLI automated layer
1. Map the study trait → EFO term (OLS term search, or GWAS Catalog trait search; or `--trait-efo-map` if user pre-mapped).
2. For each prior association in the locus, fetch its EFO traits (GWAS Catalog returns `efoTraits` per association).
3. Compute `efo_match_type`:
   - `exact` — same EFO term.
   - `parent` / `child` — OLS distance ≤ 1 (one hop in EFO hierarchy).
   - `none` — no EFO relation.
4. `auto_score`: exact → `known`; parent/child → `likely-known`; none → `novel-candidate`. Write to `candidates.json`.

### Agent judgment layer (SKILL.md workflow)
The agent reads `candidates.json` and, per locus, reviews the candidate prior reports + `efo_match_type` + the actual trait names (e.g. "type 2 diabetes" vs "fasting glucose" — Claude reasons about these semantic relations better than fixed rules). Fills `agent_judgment`: `known` / `likely-known` / `novel` + a one-line reasoning. The agent does **not** auto-declare `novel` lightly — if the automated layer and the agent disagree, or evidence is thin, it marks `likely-novel` and surfaces the prior-report list for the user.

### User confirm layer
The agent presents a verdict table (locus, lead SNP, SNP-level verdict + r² + matched catalog lead, locus-level verdict + candidate prior reports, agent judgment + reasoning). The user confirms or overrides in `user_confirmed`.

## Complementarity with COJO (must be in `references/novelty-rules.md`)

- **GCTA-COJO** (in `post-gwas-analyses`, GWASTutorial `18_Conditioning_analysis`): statistically separates independent signals **within your own sumstats** + an LD reference. Answers: *"given my sumstats, is this signal independent of the known one at this locus?"*
- **This skill** (literature query): asks whether the signal has been **reported in public databases** (GWAS Catalog). Answers: *"is this signal already in the published literature, for a same/similar phenotype?"*

One is statistical, one is bibliographic. They can agree (a signal both statistically independent and unreported = strong novel candidate) or diverge (statistically independent but already reported for a different trait = `shared-signal-different-trait`). The skill should note both angles and recommend running COJO too when the novelty verdict matters.

## Testing

- **Offline unit tests** (fixtures, no network): mock GWAS Catalog SNP-exact + region, LDlink ldproxy, OLS, and PLINK `--r2` output. Test the scoring logic:
  - exact EFO + r² ≥ 0.2 → known signal
  - r² < 0.2 against all same-phenotype leads → novel signal
  - r² ≥ 0.2 + different phenotype → `shared-signal-different-trait`
  - ±500 kb no same-phenotype prior → novel locus
  - novel signal + known locus (a same-phenotype prior in ±500 kb but r² < 0.2 with the study lead) → the combined two-level verdict
- **Live smoke test**: one real lead SNP (e.g. `rs3945628` PCOS, from the reproductive-genetics session) end-to-end, with LDlink (since no local panel in the dev env).
- **Agent-judgment layer**: validated session-style (run the skill on a known loci set, eyeball the agent's EFO judgments). Not unit-testable.

## License / attribution

- Our code: **MIT** (matches the repo).
- ClawBio `gwas-lookup`: studied under `external/` per `CLAUDE.md` (read-only reference); **no code copied**. Patterns adopted: per-API rate-limit/retry/cache, parallel dispatch via ThreadPoolExecutor, fixture-based offline tests, reproducibility bundle.
- GWASTutorial (`external/GWASTutorial`): referenced for the LDlink ldproxy call shape (`19_ld`), ±500 kb locus window (`12_fine_mapping`), GWAS Catalog EFO replication use (`41_variant_databases`), and COJO complementarity (`18_Conditioning_analysis`). Read-only reference; no code copied.
- Public APIs cited in skill metadata: GWAS Catalog (EBI REST), Ensembl REST, NCBI LDlink, EBI OLS.

## Decisions made

- **Distribution:** clean-room self-authored CLI — no vendoring of ClawBio or bio-tools code; `external/` studied as reference only.
- **Placement:** `bioinformatics/locus-novelty/` — same category as `post-gwas-analyses`, complementary (literature-query vs COJO statistical-conditional).
- **Execution model:** deterministic CLI (`locus_novelty.py`) calling public APIs directly via `httpx` (not via `bio-data` MCP) — batch-friendly, matches the 2026-08-12 session's proven pattern and ClawBio's shape. `bio-data` stays unchanged.
- **LD:** hybrid PLINK-local + LDlink ldproxy, with **explicit user consent** before LDlink fallback (no silent degradation — LDlink uses fixed 1000G populations, not ancestry-matched). LDlink call shape per GWASTutorial `19_ld`.
- **Phenotype matching:** three-tier — CLI auto-scores (EFO exact + OLS parent/child via OLS API) → agent semantic judgment → user confirm. The agent layer is the key value-add over pure-rule matching.
- **Two-level rules:** r² < 0.2 (default, `--r2-threshold` configurable) for SNP-level; ±500 kb (default, `--locus-window` configurable) for locus-level. Both configurable because the tutorial itself notes 0.1/0.05 and ±1 Mb variants.
- **Name:** `locus-novelty` (covers both levels; alternative `gwas-novelty` if a broader framing is preferred later).
- **Marketplace:** added to the `bioinformatics` plugin's skills; no `mcpServers` (pure-script skill).
