# Variant Annotation

Load when the user has GWAS hits and wants functional consequences — which genes they fall in, whether they are missense/nonsense/regulatory, and their allele frequencies across populations.

## Table of contents

- [Tools](#tools)
- [Workflow](#workflow)
- [Interpreting consequences](#interpreting-consequences)

## Tools

| Tool | Input | Strength |
|------|-------|----------|
| ANNOVAR | custom table (chr start end ref alt) | fast, scriptable, huge database set |
| VEP (Ensembl) | VCF | richest annotation, JSON output, plugins |

Both annotate against: gene models (RefSeq/Ensembl), dbSNP, ClinVar, gnomAD (population frequencies), PolyPhen/SIFT/CADD (deleteriousness), and regulatory tracks.

## Workflow

**ANNOVAR** — input is a tab-separated file with chr, start, end, ref, alt (one row per variant):
```bash
# 0_format_sumstats.sh pattern: extract variant table from sumstats
awk '{print "chr"$1"\t"$2"\t"$2"\t"$4"\t"$5}' sumstats.tsv > variants.avinput

table_annovar.pl variants.avinput humandb/ \
  -buildver hg19 \
  -out annotated \
  -remove \
  -protocol refGene,avsnp150,clinvar_20220320,gnomad211_exome \
  -operation g,f,f,f \
  -nastring .
```

**VEP** — direct VCF in, JSON/TSV out:
```bash
vep --cache --offline --assembly GRCh37 \
  --vcf -i hits.vcf -o hits.vep.vcf \
  --everything --af_gnomad --pubmed --pick
```

Both produce per-variant consequence calls; ANNOVAR outputs one row per variant with comma-separated annotations, VEP one row per variant-consequence pair (use `--pick` to reduce to one line per variant).

## Interpreting consequences

Report the consequence hierarchy honestly — a variant can be annotated as both missense (rare transcript) and intronic (common transcript):

- **Protein-altering:** missense, nonsense (stop-gain), frameshift, splice-site — the strongest candidates for causal coding effects.
- **Synonymous:** no amino-acid change — usually neutral; can still affect splicing or mRNA stability.
- **Regulatory / UTR / intronic / intergenic:** no direct protein consequence — interpret via eQTL overlap, conservation scores, or regulatory annotation.
- **Population frequency context:** a "pathogenic" ClinVar call on a variant at 30% frequency in gnomAD is almost certainly mislabeled — always pair consequence with frequency.
- **Deleteriousness scores** (CADD, SIFT, PolyPhen) are useful for prioritization but are training-based predictions, not evidence of causation.

Annotation is a hypothesis generator, not a causal statement: the variant "falls in gene X" says nothing about whether gene X is causal. Pair annotation with fine-mapping (credible set overlap) and eQTL/colocalization before claiming a gene.
