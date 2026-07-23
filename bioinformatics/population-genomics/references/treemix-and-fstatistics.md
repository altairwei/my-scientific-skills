# TreeMix and f-Statistics

TreeMix builds a maximum-likelihood population tree and adds migration edges to explain residual covariance; f3/f4/D-statistics are formal hypothesis tests for admixture and gene flow. Both work from population allele frequencies on the same SNP panel, so they share input preparation — and both are only as meaningful as the population labels and outgroup choice.

## When to use

Read this when the task involves TreeMix (population trees, migration edges, `.treeout`), f3/f4/D-statistics (ADMIXTOOLS, qpAdm, qpGraph), or testing for gene flow between populations.

## Command templates

### TreeMix input preparation

TreeMix consumes per-population allele counts. Get them from PLINK stratified frequencies:

```bash
# popmap3.txt: 3-column within-file  FID IID POP
plink --bfile OUTDIR/ld_pruned2 --freq --within OUTDIR/popmap3.txt --out OUTDIR/treemix_in
```

Then convert `.frq.strat` to TreeMix format with `plink2treemix.py` (a widely-mirrored script from the Pickrell lab; fetch it from any reputable popgen toolbox repo, verify it reads `.frq.strat[.gz]`, or write the ~15-line conversion yourself from the spec below):

```bash
python plink2treemix.py OUTDIR/treemix_in.frq.strat.gz OUTDIR/treemix.frq.gz
```

**TreeMix input format spec** (self-sufficiency fallback): first line = population names separated by spaces; then one line per SNP, with one `count1,count2` pair per population in the same order — allele counts of the two alleles in that population.

### TreeMix runs

```bash
for m in 0 1 2 3 4 5; do
  treemix -i OUTDIR/treemix.frq.gz -m $m -o OUTDIR/treemix_m${m} \
    -root OUTGROUP -k 10000 -noss > OUTDIR/treemix_m${m}.log 2>&1
done
```

Plot with the official `plotting_funcs.R` (ships with TreeMix):

```r
source("plotting_funcs.R")
pdf("treemix_m2.pdf", width=10, height=6)
plot_tree("OUTDIR/treemix_m2")
plot_resid("OUTDIR/treemix_m2", "OUTDIR/pop_order.txt")  # pop_order.txt: one population per line, tree order
dev.off()
```

### f3 / f4 / D with the ADMIXTOOLS R package

ADMIXTOOLS reads an EIGENSTRAT prefix (`.geno/.snp/.ind` — reuse the smartpca conversion from population-structure) or, in current versions, a PLINK prefix; confirm against `help(f3)` in the installed version, as the API has shifted across releases.

```r
library(admixtools)
prefix <- "OUTDIR/pca"   # pca.geno / pca.snp / pca.ind

# f3 admixture test: is TARGET admixed from sources related to SRC1 and SRC2?
f3(prefix, "TARGET", "SRC1", "SRC2")

# f4 / D: do (POPA,POPB) and (POPC,POPD) form clades, or is there gene flow?
f4(prefix, "POPA", "POPB", "POPC", "POPD", f4mode = FALSE)   # f4mode=FALSE → D-statistic
```

Population names must match the `.ind`/`.fam` labels exactly — list them first (`read_ind` / the third `.ind` column) and build test triples/quadruples from the actual labels.

## Parameter decision rules

- **Rooting (`-root`)**: use a population known a priori to be an outgroup (YRI in worldwide human panels; an archaic or sister species where available). If no defensible outgroup exists, run unrooted and say so in the interpretation.
- **Block size (`-k`)**: SNPs per jackknife block; must span more than the LD extent. 10000 suits SNP-panel densities; for dense WGS 500–1000 is acceptable. `-noss` skips a sanity check that aborts runs on small/irregular datasets.
- **Choosing m**: collect each run's final log-likelihood (run log / `.llik`) and plot likelihood vs m. Take the elbow/plateau — formalized by OptM (pick the m explaining ≥ ~99.8% of variance). Then inspect residuals (`plot_resid`): large residual covariance between a pair means the graph still mis-models them; an m whose migration arrows sit on top of large residuals is underfit, one with arrows but no residuals is overfit. Present the likelihood table to the user.
- **Node support**: for bootstrap, generate block-bootstrap replicates (`-bootstrap`), rerun the chosen m, and summarize with a consensus tree; report support on key splits.
- **f3 interpretation**: f3(TARGET; SRC1, SRC2) significantly **negative** (Z < −3) supports TARGET being admixed between the source lineages. Non-negative f3 does not prove no admixture (power limits).
- **f4/D interpretation**: |Z| > 3 = significant. D ≠ 0 (e.g. D(A,B;C,OUT)) means excess allele sharing between one side and C — i.e. gene flow; the sign tells the direction. f4 ≈ 0 is consistent with tree-like relationships.
- **qpAdm/qpGraph (brief)**: qpAdm tests whether a target can be modeled as a mixture of the proposed sources given outgroups (p > 0.05 = model not rejected — test several source sets, not one); qpGraph fits an explicit admixture graph by f4 residuals (worst |Z| ≲ 3 = acceptable fit). Both need careful outgroup sets — consult the ADMIXTOOLS documentation before running.

## Output verification checklist

- `treemix.frq.gz` line count = SNP count + 1 (header); population count in header = populations in `popmap3.txt`.
- Per m: `treemix_m${m}.{treeout,vertices,edges,cov,covse}` exist; the log shows likelihood convergence.
- Likelihood extracted for every m before choosing (never pick m by habit).
- f3/f4 output tables contain estimate, standard error, and Z — report all three.

## Figure reading guide

- **TreeMix tree**: topology = drift history (splits ≈ divergences); branch length ≈ drift amount. Migration arrows: direction = source → recipient of gene flow; color/width = migration weight. Read arrows together with residuals, never alone.
- **Residual heatmap**: bright spots = population pairs whose covariance the graph fails to explain — candidate gene-flow events.
- **f3/f4 bar charts with error bars**: a result is only as strong as its Z; plot Z alongside the estimate.

## Common pitfalls

- Population-label mismatches between `.fam`, `popmap3.txt`, and the R calls — silent subsetting or wrong tests.
- Interpreting migration edges without checking residuals or trying the next m up.
- Comparing D-statistics computed on different SNP sets or different ascertainment panels.
- TreeMix on populations of 1–2 individuals: allele-count noise dominates; treat resulting trees as exploratory.
