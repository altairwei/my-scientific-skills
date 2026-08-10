# Gene-Based and Gene-Set Analysis: MAGMA

Load when the user has GWAS sumstats and wants gene-level association (which genes harbor signal) or pathway/gene-set enrichment (which functional sets are enriched).

## Table of contents

- [Workflow](#workflow)
- [Reference commands](#reference-commands)
- [Interpreting results](#interpreting-results)

## Workflow

MAGMA tests each gene by aggregating variant-level association evidence, then tests gene sets (pathways) for enrichment. Three steps:

1. **Annotate** SNPs to genes — the SNP-to-gene window is critical: `window=35,10` means 35 kb upstream + 10 kb downstream of the gene body. Window choice trades sensitivity (wide windows catch distal regulatory SNPs) against specificity (wide windows attribute neighboring-gene signal).
2. **Gene-based test** — aggregates per-gene SNP P values into a gene-level statistic. MAGMA's default is a multiple linear principal-components regression (SNP-by-SNP model with LD); the summary-statistics mode (snp-wise mean model) needs a reference panel for LD but not individual genotypes.
3. **Gene-set analysis** — competitive test: are genes in the set more associated than genes outside it? Use curated sets (MSigDB, GO) and correct for the number of sets tested.

## Reference commands

```bash
# 1. Format input from sumstats: SNP, CHR, BP  and  SNP, P
awk '{print $1,$2,$3}' sumstats.tsv > snp.chr.pos.txt
awk '{print $1, 10^(-$6)}' sumstats.tsv > snp.pval.txt      # P already -log10 → convert

# 2. Annotate SNPs to genes
magma --annotate \
  --snp-loc snp.chr.pos.txt \
  --gene-loc NCBI37.3.gene.loc \
  --out study_chr3

# 3. Gene-based test (needs a reference bfile for LD; N = cohort size)
magma --bfile g1000_eas \
  --pval snp.pval.txt N=70657 \
  --gene-annot study_chr3.genes.annot \
  --out study_chr3

# 4. Gene-set analysis on the gene results
magma --gene-results study_chr3.genes.raw \
  --set-annot msigdb.v2022.1.Hs.entrez.gmt \
  --out study_chr3
```

- The reference bfile (`--bfile`) must be the same ancestry as the cohort (see sumstats-basics) — LD is computed from it for the SNP-wise model.
- `--pval N=<n>`: per-gene N is derived from the sumstats' own N when present (`--pval-ncol`); do not fabricate N.
- Gene-based significance: Bonferroni over ~20k genes (≈ 2.5×10⁻⁶); gene-set significance: Bonferroni/FDR over the sets tested.

## Interpreting results

- Gene-level hits are *aggregations* of variant signal — a top gene is not evidence that the gene itself is causal (a strong nearby variant with a wide window can drive it). Pair with fine-mapping and eQTL/colocalization before claiming causality.
- The gene-set test is **competitive** by default (genes in set vs rest) — a "significant pathway" means enrichment relative to the genome, not that the pathway explains the trait.
- Report: number of genes tested, window used, LD reference used, and the multiple-testing correction applied. These details determine whether a result is comparable across studies.
