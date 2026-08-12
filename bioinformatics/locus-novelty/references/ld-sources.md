# LD sources: PLINK local vs LDlink

## PLINK local (preferred when a panel is available)

`plink --bfile <prefix> --r2 inter-chr --extract <snps> --ld-window-r2 0 --ld-window 999999 --ld-window-kb 1000`

- Accurate, ancestry-matched to your cohort, offline.
- Requires: a PLINK bfile reference panel (e.g. 1000G, TOPMed, or your cohort's
  own imputed dosages) + PLINK installed.
- `post-gwas-analyses` already treats "is an LD reference panel available" as a
  standard prerequisite — reuse that panel here.

## LDlink LDproxy (fallback — ask before using)

`GET https://ldlink.nci.nih.gov/LDlinkRest/ldproxy?var={rsid}&pop={ancestry}&r2_d=r2&window=500000&genome_build=grch38&token={NCBI_API_KEY}`

- Pure API, no local data; returns r² of the query SNP vs proxies in a 500 kb
  window (1000G `<ancestry>` population).
- **Not strictly ancestry-matched** — 1000G populations are coarse (EUR, AFR,
  AMR, EAS, SAS). That's why the SKILL.md workflow requires explicit user
  consent before falling back to LDlink.
- Rate-limited; `NCBI_API_KEY` raises the limit (3→10 req/s) — optional but
  recommended; read from the shell environment.
- Call shape per GWASTutorial `19_ld` (external/, read-only reference).
