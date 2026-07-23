# Preprocessing and Quality Control

Population-genetics statistics assume independent, high-quality SNPs genotyped in unrelated individuals. Skipping or reordering these steps invalidates downstream numbers in ways that are hard to detect later — a kinship estimate computed on LD-correlated SNPs, or a PCA run on related individuals, looks fine but means something else.

## When to use

Read this when the task involves: converting VCF ↔ PLINK formats, filtering variants or samples, LD pruning, or detecting/removing related individuals (KING, kinship, `.kin0`).

## Command templates

In all templates, replace `OUTDIR` with the session output directory. Verify tool availability first (`which plink king`); if missing, propose `conda install -c bioconda plink king` and wait for consent.

### VCF → PLINK binary

```bash
plink --vcf input.vcf.gz --double-id --allow-extra-chr \
  --set-missing-var-ids @:# --make-bed --out OUTDIR/raw
```

- `--double-id` copies the sample name into both ID fields (VCF has no two-ID structure).
- `--set-missing-var-ids @:#` names unnamed variants `chr:pos` — required because many downstream steps key on variant ID.
- `--allow-extra-chr` is for non-human assemblies; drop it for human data.
- For BCF or large VCFs, `plink2 --vcf` or `bcftools` conversion is faster; the flags above are PLINK 1.9.

### Quality filtering

```bash
plink --bfile OUTDIR/raw \
  --maf 0.05 --geno 0.05 --mind 0.1 --biallelic-only strict \
  --make-bed --out OUTDIR/filtered
```

### LD pruning — two rounds, two purposes

Round 1 (r² = 0.2) — SNP set for kinship estimation and diversity statistics:

```bash
plink --bfile OUTDIR/filtered --indep-pairwise 50 5 0.2 --out OUTDIR/prune1
plink --bfile OUTDIR/filtered --extract OUTDIR/prune1.prune.in \
  --make-bed --out OUTDIR/ld_pruned1
```

Round 2 (r² = 0.1, stricter, applied to the *unrelated* set) — for PCA and ADMIXTURE, which assume unlinked markers:

```bash
plink --bfile OUTDIR/unrelated --indep-pairwise 50 5 0.1 --out OUTDIR/prune2
plink --bfile OUTDIR/unrelated --extract OUTDIR/prune2.prune.in \
  --make-bed --out OUTDIR/ld_pruned2
```

`--indep-pairwise 50 5 X` means: 50-SNP window, slide 5 SNPs per step, prune one of each pair with r² above X.

### Kinship detection and relatedness removal (KING)

```bash
king -b OUTDIR/ld_pruned1.bed --related --prefix OUTDIR/kinship
```

Then remove one member of each related pair. The `kinship.kin0` file has a header naming its columns (`FID1`, `ID1`, `FID2`, `ID2`, …, `Kinship`) — read the header rather than assuming fixed column positions, and choose the member with lower call rate (or more relatives) per pair. Feeding both members of every pair to `--remove` would delete entire families.

```bash
# after building related_to_remove.txt (one FID IID pair per line, one individual per pair)
plink --bfile OUTDIR/filtered --remove OUTDIR/related_to_remove.txt \
  --make-bed --out OUTDIR/unrelated
```

Modern one-step alternative: `plink2 --bfile OUTDIR/ld_pruned1 --king-cutoff 0.0884 --make-bed --out ...` implements KING-robust estimation with built-in greedy removal (cutoff 0.0884 ≈ up to 3rd-degree relatives).

## Parameter decision rules

**QC thresholds (defaults — adjust with a stated reason and record the choice):**

- `--maf 0.05`: removes rare variants that add noise to structure analyses. For diversity statistics on large cohorts, 0.01 is also defensible.
- `--geno 0.05`: drop SNPs with >5% missing calls; `--mind 0.1`: drop samples with >10% missing.
- `--biallelic-only strict`: multiallelic sites break ADMIXTURE/TreeMix/f-statistics assumptions.
- Filter samples and SNPs in one pass so thresholds apply jointly.

**Kinship coefficient (φ) tiers:**

| φ range | Relationship |
|---|---|
| > 0.354 | duplicate / monozygotic twin |
| 0.177–0.354 | 1st degree |
| 0.0884–0.177 | 2nd degree |
| 0.0442–0.0884 | 3rd degree |

**Ordering rationale:**

- Run KING on the round-1 LD-pruned set — relatedness estimates are inflated by LD.
- Remove relatives from the *filtered* (unpruned) set, keeping maximum SNP density for diversity statistics. The `unrelated` set feeds both diversity stats and round-2 pruning.
- PCA/ADMIXTURE get the stricter round-2 set; diversity statistics tolerate (and benefit from) more SNPs.

## Output verification checklist

- `filtered.{bed,bim,fam}` exist; SNP/sample counts in the PLINK log are lower than raw but not catastrophically (a >50% SNP drop usually means a threshold or chromosome-naming problem).
- `prune1.prune.in` / `prune2.prune.in` are non-empty. Empty output = threshold too strict for the data density or too few SNPs — loosen r² or widen the window.
- `kinship.kin0` exists. An empty (header-only) file means no related pairs — a valid result, not an error.
- After removal: `unrelated.fam` line count + removed count = `filtered.fam` line count.
- Report per-population sample counts after `unrelated`; flag any population that has collapsed.

## Figure reading guide

QC is mostly numeric, but two diagnostic plots are worth making when the data is unfamiliar:

- **MAF spectrum** (histogram of `--freq` output): a healthy panel has mass spread across frequencies; a huge spike near 0 after `--maf 0.05` suggests genotyping artifacts survived filtering.
- **Per-sample missingness vs heterozygosity** (from `--missing` + `--het`): outlier samples off the cloud = contamination, wrong species/relatives, or failed DNA — remove them before proceeding.

## Common pitfalls

- Forgetting `--set-missing-var-ids` → duplicate/missing variant IDs break `convertf` and TreeMix input preparation downstream.
- Pruning order: QC → prune1 → KING → remove → prune2. Removing relatives *before* KING (from the wrong file set) or pruning structure SNPs from the related set are the two classic mistakes.
- Chromosome naming mismatches (`chr1` vs `1`) between VCF and any auxiliary reference files silently drop all variants.
- `--mind` can remove many low-coverage samples — check *which* populations lost samples before proceeding.
