# Design: `population-genomics` Skill (distilled from PopGenAgent)

Date: 2026-07-23
Status: Approved by user (structure + scope + harness adaptation)

## Goal

Distill the reusable population-genomics expertise of `external/POPGENAGENT`
(PopGenAgent) into a single "experience-type" skill in this repository. The
skill captures the *hard-won agent/domain tuning knowledge* — orchestration
discipline, command templates, parameter decision rules, and tool gotchas —
rather than re-implementing PopGenAgent's LangChain pipeline or fixing one
rigid end-to-end workflow.

Per repository policy, all content is written originally for this repo. No
files are copied from `external/`; third-party vendored scripts in PopGenAgent
(easySFS.py, plink2treemix.py, plotting_funcs.R) are *referenced* (where to
obtain, how to use), never vendored.

## Source analysis (what PopGenAgent actually is)

PopGenAgent is a multi-agent LLM system for population genomics:

1. **Plan agent** — maps a natural-language goal + data manifest (file paths
   with one-line descriptions) to an ordered JSON plan, using a recipe library
   (`Plan_Knowledge.json`): a canonical 20-step full workflow plus focused
   sub-workflows (qc-only, pca-only, admixture-only, diversity, treemix+fstats,
   kinship-only). Steps are tagged `[ANALYSIS]` or `[VISUALIZATION]` and declare
   expected outputs.
2. **Task agent** — instantiates each plan step into a concrete, auditable
   shell script from command templates + tool docs (`knowledge/tool/`, ~80
   docs), then executes it with bash.
3. **Check agent** — after each step, verifies expected output files exist and
   are non-empty; if missing, scans the directory and re-identifies actual
   outputs.
4. **Debug agent** — on failure, collects script + stderr + expected outputs,
   diagnoses root cause, emits a repaired script; bounded retries.
5. **Post-hoc agents** — vision-based interpretation of PCA/ADMIXTURE/TreeMix
   figures into reports; a modeling agent synthesizes reports into a
   fastsimcoal2 modeling strategy; an integrated workflow iterates fastsimcoal2
   runs with likelihood-driven search rules, then exports a Demes model.

The reusable "磨合" (tuning) knowledge distills into three layers:

- **Orchestration discipline**: plan before acting; separate analysis vs
  visualization steps; verify every step's outputs before continuing; debug
  with full context (script + stderr + expectations); bounded retries;
  provenance for everything.
- **Domain decision rules**: two-tier LD pruning (r² 0.2 for kinship/structure
  prep, 0.1 for PCA/ADMIXTURE); KING kinship cutoffs (0.354 / 0.177 / 0.0884 /
  0.0442); ADMIXTURE K selection by minimum CV error; f3/D significance at
  |Z| > 3; TreeMix m = 0..5 sweep with outgroup rooting; easySFS projection
  rule (v = even(n−2), clipped to 2..70); fastsimcoal2 anti-hang rules
  (TEXP < all TDIV; no times > 10,000 generations; parameter names must not be
  substrings of each other; migration ≤ 0.01); likelihood-driven model search
  (parameter at boundary → expand range; small improvement → bigger moves).
- **Tool gotchas**: EIGENSTRAT conversion for smartpca; ADMIXTURE output file
  naming; TreeMix input requires plink2treemix allele-count format; fsc28
  .tpl/.est structural constraints.

## Tool documentation policy

PopGenAgent ships ~80 raw tool docs in `knowledge/tool/` (with duplicates —
e.g. `ROH.txt`/`ROH1.txt`, three LD-pruning files) as a RAG corpus: its LLM
needed retrieval grounding to avoid hallucinating niche tool usage.

This skill deliberately does NOT reproduce that corpus, because:

1. Repo policy: no verbatim copies from `external/` (license + originality).
2. Redundancy: most of that content duplicates `tool --help` output, official
   docs, and Claude's existing knowledge.
3. Version drift: static docs describe some version of a tool, while the
   installed binary's `--help` is ground truth. Claude Code can consult live
   help output and official docs at runtime — a capability PopGenAgent's
   static RAG lacked. Copied stale docs would become an error source.

What IS carried over: the distilled, experience-bearing content of those docs
(command recipes, thresholds, file-format pitfalls) lives in the five
references. Each reference must be **self-sufficient** for the tools it
covers: for failure-prone, version-sensitive, or thinly-documented tools
(smartpca/convertf EIGENSTRAT formats, fsc28 `.tpl`/`.est` grammar, easySFS
CLI, ADMIXTOOLS R calls), the reference includes the format specs and CLI
idioms in full, written originally.

Corollary working discipline (goes into SKILL.md): before writing a command
for a tool whose exact flags are uncertain, run `tool --help` or consult
official documentation first — ground the command, don't recall it.

## Harness adaptation (Claude Code, not LangChain)

The orchestration discipline is expressed as native Claude Code behavior:

| PopGenAgent agent | Claude Code adaptation |
|---|---|
| Plan agent (JSON plan) | Confirm goal + data manifest with the user; track steps with TaskCreate |
| Task agent (Step_i.sh) | Run steps via Bash, one auditable command per step; no monolithic pipelines |
| Check agent | After each step, verify expected outputs exist and are non-empty; skim the log |
| Debug agent | On failure, read stderr/log, consult the relevant reference's decision rules, fix and retry; after 2–3 failed repairs, stop and report the diagnosis to the user |
| RAG over tool docs | `references/` progressive disclosure — Read the topical file on demand |
| Vision interpretation agent | Read generated PNG/PDF figures directly; interpret per the reference's reading guide |
| `output/<session>/` provenance | Recommend a dedicated output directory in the user's project; scripts and logs written to disk for reproducibility |

## Skill structure

```
bioinformatics/population-genomics/
├── SKILL.md                      # ~150–200 lines, < 5000 tokens
└── references/
    ├── preprocessing-and-qc.md
    ├── diversity-statistics.md
    ├── population-structure.md
    ├── treemix-and-fstatistics.md
    └── demographic-inference.md
```

### SKILL.md outline

- **Frontmatter**: `name: population-genomics`; `description` covers concrete
  triggers — VCF/PLINK (bed/bim/fam) files, PCA, ADMIXTURE, TreeMix,
  f3/f4/D-statistics, ROH, heterozygosity, LD decay, FST, fastsimcoal/demes,
  "population structure", "群体结构" phrasings; slightly pushy per repo
  convention; < 100 tokens. `metadata` (author, version), `license: MIT`.
- **Positioning**: this is field experience, not a fixed pipeline — select a
  focused workflow from the user's goal; ask when the goal is ambiguous.
- **Working discipline** (the harness adaptation table above, as prose/bullets,
  plus the grounding rule from the Tool documentation policy).
- **Workflow map**: the canonical 20-step core workflow as a table, each row
  annotated with which reference file covers it; plus focused-workflow
  shortcuts (qc-only → preprocessing ref; pca/admixture → structure ref; etc.).
- **Data contract**: expected inputs (PLINK binary, VCF), output-directory
  convention, raw data immutability.
- **Further analyses** (one-liner pointers only): qpAdm/qpGraph, PSMC/MSMC,
  selection scans (iHS/XP-EHH).

### References (uniform section structure)

Each reference: **When to use → Command templates → Parameter decision rules →
Output verification checklist → Figure reading guide → Common pitfalls.**
Each reference is self-sufficient for its tools (see Tool documentation
policy): file-format specs and CLI idioms for failure-prone tools are included
in full rather than assumed known.

1. `preprocessing-and-qc.md` — PLINK QC thresholds (`--maf 0.05 --geno 0.05
   --mind 0.1 --biallelic-only strict`); two-round LD pruning (r² 0.2 vs 0.1
   and what each round serves); KING relatedness (four kinship tiers) and
   related-individual removal.
2. `diversity-statistics.md` — ROH (`--homozyg` parameter family), observed
   heterozygosity (`--het`), per-population LD decay (`--r2` + 10 kb binning),
   FST.
3. `population-structure.md` — PLINK→EIGENSTRAT conversion, smartpca parameter
   file and outputs, ADMIXTURE K sweep + CV-error K selection, visualization
   and interpretation of PCA/ADMIXTURE results.
4. `treemix-and-fstatistics.md` — TreeMix input preparation (plink2treemix),
   m = 0..5 sweep with outgroup rooting and likelihood comparison, bootstrap;
   ADMIXTOOLS f3/f4/D-statistics with |Z| > 3 interpretation; qpAdm/qpGraph in
   brief.
5. `demographic-inference.md` — easySFS projection rule; fastsimcoal2 .tpl/.est
   structure and anti-hang/anti-crash rules; likelihood-driven model search;
   Demes export.

## Data flow (typical session)

User provides VCF/PLINK data + goal → confirm data manifest (format, samples,
population groupings) → propose a focused plan (TaskCreate) → execute step by
step (run → verify outputs → next) → Read key figures and interpret → close
with a written summary (findings + recommended next steps).

## Error handling

- Missing tool → detect (`which`/`conda list`), propose bioconda install,
  wait for user consent.
- Expected output missing/empty → inspect log, fix against reference rules,
  retry; 2–3 consecutive failures → stop and report diagnosis, no infinite
  loop.
- Decision points (best K, best m, projection sizes) → present evidence
  tables (CV errors, likelihoods) and let the user decide.

## Testing & registration

1. `./count-skill-tokens.py bioinformatics/population-genomics` — SKILL.md <
   5000 tokens / 500 lines, description < 100 tokens.
2. Local trigger test: copy to `~/.claude/skills/`, start a fresh session;
   positive prompts ("analyze population structure in this VCF", "run
   ADMIXTURE") should trigger; negative prompts ("QC my RNA-seq reads")
   should not.
3. Register under the `bioinformatics` plugin in
   `.claude-plugin/marketplace.json`; add the skill to the README.md category
   table (and plugin install line if needed).
4. No `scripts/` directory in v1 — all helpers are either standard tools
   (bioconda) or trivial one-liners kept inline in references.

## Out of scope (v1)

- Vendoring or rewriting PopGenAgent's third-party helper scripts.
- Detailed qpAdm/qpGraph, PSMC/MSMC, iHS/XP-EHH guides (pointed at only).
- Replicating PopGenAgent's Web UI, API pool, or PubMed RAG features.
