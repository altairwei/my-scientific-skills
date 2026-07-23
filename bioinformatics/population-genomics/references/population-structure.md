# Population Structure: PCA and ADMIXTURE

PCA and ADMIXTURE are the two workhorse views of population structure. Their shared assumption — unlinked SNPs in unrelated individuals — is why they consume the strict round-2 LD-pruned set (`ld_pruned2`). Violating that assumption does not error out; it manufactures clusters and ancestry components that are not there.

## When to use

Read this when the task involves PCA (smartpca, EIGENSTRAT, `.evec`), ancestry estimation (ADMIXTURE, `.Q` files, choosing K), or interpreting structure plots.

## Command templates

### smartpca (EIGENSOFT)

1. Convert PLINK → PED (1/2-coded):

```bash
plink --bfile OUTDIR/ld_pruned2 --recode 12 --out OUTDIR/pca_temp
```

2. Write `OUTDIR/par.convertf` (convertf derives the `.ind` from the PED):

```text
genotypename:    OUTDIR/pca_temp.ped
snpname:         OUTDIR/pca_temp.map
indivname:       OUTDIR/pca_temp.ped
outputformat:    EIGENSTRAT
genotypeoutname: OUTDIR/pca.geno
snpoutname:      OUTDIR/pca.snp
indivoutname:    OUTDIR/pca.ind
```

Run `convertf -p OUTDIR/par.convertf`. This generates `pca.geno`, `pca.snp`, and `pca.ind` — the `.ind` third column comes from the `.ped` phenotype column (often `1`/`2` or `-9`), so set population labels next.

3. Set population labels in `pca.ind`. The `.ind` has three whitespace-separated columns (`sample_id  sex  label`); replace the third column with the population label from `popmap.txt` (`IID <tab> POP`). One way:

```bash
awk 'NR==FNR {pop[$1]=$2; next} {print $1, $2, pop[$1] ? pop[$1] : "U"}' \
  OUTDIR/popmap.txt OUTDIR/pca.ind > OUTDIR/pca.ind.labeled && \
  mv OUTDIR/pca.ind.labeled OUTDIR/pca.ind
```

These labels drive smartpca's outlier removal (per-population) and PCA plotting — leaving them as `1`/`2` makes both useless.

4. Write `OUTDIR/par.smartpca`:

```text
genotypename:   OUTDIR/pca.geno
snpname:        OUTDIR/pca.snp
indivname:      OUTDIR/pca.ind
evecoutname:    OUTDIR/pca_results.evec
evaloutname:    OUTDIR/pca_results.eval
numoutevec:     20
numoutlieriter: 5
altnormstyle:   YES
```

5. Run:

```bash
smartpca -p OUTDIR/par.smartpca > OUTDIR/smartpca.log 2>&1
```

Quick alternative when EIGENSOFT is unavailable: `plink2 --bfile OUTDIR/ld_pruned2 --pca 20 --out OUTDIR/pca` produces `.eigenvec`/`.eigenval` — fine for exploration, but smartpca adds Tracy–Widom significance and iterative outlier removal.

### ADMIXTURE

```bash
cd OUTDIR   # ADMIXTURE writes .Q/.P into the CURRENT directory, named after the input basename
for K in 2 3 4 5 6 7 8 9 10 11 12; do
  admixture --cv -s 42 -j4 ld_pruned2.bed $K > admixture_k${K}.log 2>&1
  mv ld_pruned2.${K}.Q admixture_k${K}.Q
  mv ld_pruned2.${K}.P admixture_k${K}.P
done
grep -h "CV error" admixture_k*.log > cv_errors.txt
```

## Parameter decision rules

- **smartpca**: `numoutevec: 20` covers any realistic structure; `numoutlieriter: 5` removes PCs driven by a handful of outliers (set to 0 only if the user asks to keep outliers); `altnormstyle: YES` is the recommended normalization for EIGENSOFT ≥ 6.
- **Choosing K**: pick the K with the lowest CV error — then still look at the neighbors. CV frequently declines monotonically on large datasets; in that case report the elbow plus one K below/above, and prefer the K whose components are biologically interpretable. Present the CV table to the user and decide together.
- **K sweep cost**: K values are independent runs — run them concurrently (or with `-j` threads each) rather than serially on large panels.
- **Reproducibility**: fix `-s 42` (default seeds from the clock).

## Output verification checklist

- `pca_results.eval` has 20 eigenvalues; `pca_results.evec` has samples+1 lines (first line = eigenvalues; then one line per sample: ID, eigenvector entries, population label last).
- `smartpca.log` ends normally and lists Tracy–Widom statistics — count how many PCs are significant (p < 0.05); that bounds how many PCs to plot and discuss.
- For every K: `admixture_k${K}.Q` line count = `ld_pruned2.fam` line count, and each row sums to ≈ 1.
- `cv_errors.txt` has one line per K.

## Figure reading guide

- **PCA biplot (PC1 vs PC2, colored by population)**: check variance explained per PC from `.eval` first — if PC1+PC2 explain < a few percent, structure is weak or homogeneous and over-interpretation is the main risk. Tight clusters matching known groups = discrete structure; gradients = isolation-by-distance; isolated single points = recent admixture, batch effects, or missed relatives (go back to the kinship step before believing them).
- **Ancestry bar plot (stacked `.Q`, samples grouped by population)**: read at the agreed K. Solid blocks = discrete ancestry; systematically mixed bars across a whole population = shared admixture history or gene flow; a component carried by one or two individuals = likely artifact of small sample size, not a "ghost population".
- Cross-check PCA and ADMIXTURE against each other: clusters on PCA should roughly correspond to dominant components. Disagreement usually means LD/relatedness leaked into the input set.

## Common pitfalls

- Running PCA/ADMIXTURE on `filtered` or `ld_pruned1` instead of `ld_pruned2` — unlinked-markers assumption broken, spurious clusters.
- ADMIXTURE's silent cwd behavior: `.Q`/`.P` appear next to where you ran it, named `<basename>.<K>.Q` — the `cd OUTDIR` + `mv` pattern above is deliberate.
- `.Q` rows are in `.fam` order — align samples to populations via the `.fam`, never by guesswork.
- Reporting only the CV-minimal K without inspecting bar plots: the statistical optimum and the interpretable answer often differ by ±1–2 K.
- Leaving `.ind` labels as `1`/`2` from convertf — set them from the population map so outlier removal and plotting work.
