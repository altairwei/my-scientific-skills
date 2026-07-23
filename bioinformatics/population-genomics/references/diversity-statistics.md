# Diversity Statistics

Runs of homozygosity, heterozygosity, LD decay, and FST answer "how much variation, how is it structured, and how did drift act on it?" They are computed on the QC'd, relatedness-removed (`unrelated`) set — related individuals double-count segments and deflate diversity.

## When to use

Read this when the task involves ROH (runs of homozygosity, inbreeding, F_ROH), observed heterozygosity, LD decay curves, or FST between populations.

## Command templates

All commands assume `OUTDIR/unrelated` from preprocessing-and-qc. A population map (`popmap.txt`: one `IID <tab> POP` per line, derived from the `.fam` or supplied by the user) is needed for per-population work.

### Runs of homozygosity (ROH)

```bash
plink --bfile OUTDIR/unrelated --homozyg \
  --homozyg-snp 50 --homozyg-kb 500 --homozyg-density 50 \
  --homozyg-gap 1000 --homozyg-window-snp 50 \
  --homozyg-window-het 1 --homozyg-window-missing 5 \
  --out OUTDIR/roh_segments
```

Per-individual inbreeding: F_ROH = (sum of ROH lengths in kb, typically segments ≥ 500 kb–1 Mb) / (total genotyped autosomal length in kb; ≈ 2.88×10⁶ kb for human, scale to your species).

### Heterozygosity

```bash
plink --bfile OUTDIR/unrelated --het --out OUTDIR/heterozygosity_stats
```

The `.het` columns are `FID IID O(HOM) E(HOM) N(NM) F`. Observed heterozygosity rate = (`N(NM)` − `O(HOM)`) / `N(NM)`. The `F` coefficient: positive F = homozygote excess (inbreeding/drift), negative F = heterozygote excess (outbreeding/recent admixture).

### LD decay (per population)

```bash
plink --bfile OUTDIR/unrelated \
  --keep OUTDIR/POP_samples.txt \
  --r2 --ld-window 999999 --ld-window-kb 500 --ld-window-r2 0.0 \
  --out OUTDIR/ld_decay/POP_ld
```

Then bin SNP pairs by physical distance (e.g. 10-kb bins out to 500 kb) and average r² per bin; plot all populations' decay curves on shared axes. PopLDdecay produces the same plot directly and is a good cross-check.

### FST

Pairwise, windowed (classic route):

```bash
vcftools --gzvcf cohort.vcf.gz \
  --weir-fst-pop pop1.txt --weir-fst-pop pop2.txt \
  --fst-window-size 100000 --fst-window-step 50000 \
  --out OUTDIR/fst_pop1_pop2
```

Genome-wide multi-population (modern route):

```bash
plink2 --bfile OUTDIR/unrelated --fst --within popmap3.txt --out OUTDIR/fst
```

(`popmap3.txt` is the 3-column `FID IID POP` within-file. plink2's default FST is the Hudson estimator; `--fst method=wc` gives Weir–Cockerham.)

## Parameter decision rules

- **ROH parameters are density-dependent.** The defaults above suit SNP-array-scale human data (~500k SNPs). For denser WGS panels raise `--homozyg-snp` and `--homozyg-kb` (e.g. 100 SNP / 1000 kb) so that short, ancient background homozygosity is not called as ROH. State the parameters used when reporting F_ROH — values are comparable only within the same settings.
- **Long vs short ROH**: long segments (≥ 1–2 Mb) signal recent inbreeding; many short segments signal old background relatedness/small long-term Ne. Report both the length spectrum and the total.
- **LD decay**: use `--ld-window-r2 0.0` to keep all pairs (the default 0.2 truncates the informative tail). Each population needs ≥ ~20 individuals for stable r² averages.
- **FST**: treat small negative estimates as 0. Use windowed scans for outlier detection; use the genome-wide mean for population comparison. FST from the LD-pruned structure set and the full unrelated set should agree qualitatively — report which set was used.

## Output verification checklist

- `roh_segments.hom` (segments), `.hom.indiv` (per-sample sums) exist and are non-empty; every sample appears in `.hom.indiv` (zero-ROH samples included).
- `heterozygosity_stats.het` has one row per sample.
- `POP_ld.ld` has millions of rows for typical panels; spot-check that distances span 0–500 kb.
- FST outputs: `.weir.fst` (per-SNP) / `.windowed.weir.fst` (windows) from vcftools; `.fst` / `.fst.summary` from plink2.

## Figure reading guide

- **F_ROH per population (boxplot or bar)**: higher = more inbreeding. A population with wide spread has mixed histories within the group.
- **ROH count vs total length scatter** (one point per individual): points up-and-right with long segments = recent inbreeding; many segments but short total = ancient small Ne.
- **Observed heterozygosity per population**: lower = more drift/lower Ne. Compare against F sign, not just the rate.
- **LD decay curves**: faster decay = larger long-term Ne. A curve sitting above the others at all distances = smaller Ne or a recent bottleneck. Curves that fail to approach baseline by 500 kb suggest strong recent structure or few samples.

## Common pitfalls

- Computing ROH or heterozygosity before removing relatives — relatedness inflates both.
- Comparing F_ROH across datasets filtered with different `--homozyg-*` settings.
- LD decay on fewer than ~15–20 individuals per population: r² averages become sample-noise.
- Interpreting mean FST without noting ascertainment: SNP-array panels (pre-selected common SNPs) bias FST downward relative to WGS.
