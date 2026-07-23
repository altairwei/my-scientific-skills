# Demographic Inference: easySFS, fastsimcoal2, Demes

Site-frequency-spectrum (SFS) methods infer population sizes, divergence times, and migration from the joint allele-frequency distribution. fastsimcoal2 is powerful but famously unforgiving: malformed `.tpl`/`.est` files do not error — they hang forever or segfault. The rules below exist because each one has burned an analyst before; follow them exactly.

## When to use

Read this when the task involves the site frequency spectrum (SFS), easySFS, fastsimcoal2/fsc28 (`.tpl`, `.est`, `.obs`), demographic models (bottleneck, expansion, divergence, migration), or exporting models to Demes.

## Command templates

### 1. Build the SFS with easySFS

Population file: two whitespace-separated columns `sample_id population`.

```bash
python easySFS.py -i cohort.vcf.gz -p pops.txt --preview          # inspect projections & SNP yield
python easySFS.py -i cohort.vcf.gz -p pops.txt --proj 20,20,20 -o OUTDIR/sfs -f
```

Outputs: `dadi/*.sfs` and `fastsimcoal2/` — `POP_MSFS.obs` (multi-pop) or `POP1_jointMAFpop1_0.obs` (2-pop marginal). easySFS is not vendored here — install from its author repo (isaacovercast/easySFS).

### 2. Run fastsimcoal2

fsc28 locates the observed SFS **by the .tpl basename**: `PREFIX_MSFS.obs` (multi-pop) or `PREFIX_jointMAFpop1_0.obs` must sit in the run directory.

```bash
cd OUTDIR/run
cp ../sfs/fastsimcoal2/PREFIX_MSFS.obs .
fsc28 -t PREFIX.tpl -e PREFIX.est -m -M -n100000 -L40 -c12 -q > PREFIX.log 2>&1
```

- `-m` = folded (MAF) SFS — matches easySFS's default folded output; `-d` is for unfolded/polarized spectra.
- `-M` = likelihood maximization; `-n` simulations per evaluation (100000); `-L` optimization cycles (40); `-c` threads.
- One run is one point estimate: repeat with different seeds (≥ 10 exploratory, 40–100 for production) and keep the best-likelihood replicate.

### 3. Minimal working `.tpl` (2-pop divergence, constant sizes)

```text
//Number of population samples (demes)
2
//Population effective sizes (number of genes)
NPOP0
NPOP1
//Sample sizes (numbers of gene copies)
20
20
//Growth rates: negative growth = expansion backward in time
0
0
//Number of migration matrices
1
//Migration matrix 0
0 MIG
MIG 0
//Historical events: time, source, sink, migrants, new size, new growth, migr matrix
1 historical event
TDIV 0 1 1 RESIZE 0 0
//Number of independent loci [chromosomes]
1 0
//Per chromosome: data type, number of loci, recombination rate, mutation rate
FREQ 1 0 2.5e-8 OUTEXP
```

The historical-event line `TDIV 0 1 1 RESIZE 0 0` reads backward in time: at generation TDIV, 100% of pop 0 merges into pop 1 (= a forward-time divergence), and the sink is resized by factor RESIZE.

### 4. Matching `.est`

```text
// Priors and rules file

[PARAMETERS]
//#isInt? #name  #dist.    #min  #max
//all N are in numbers of haploid individuals
1  NPOP0  logunif  100   100000  output
1  NPOP1  logunif  100   100000  output
1  ANC    logunif  100   100000  output
0  TDIV   unif     2000  6000    output
0  MIG    logunif  1e-5  5e-4    output

[COMPLEX PARAMETERS]
0  RESIZE = ANC / NPOP1  hide
```

## Parameter decision rules

**easySFS projection** (per population): choose the largest even number ≤ (2 × individuals − 2), clipped to [2, 70]. Always `--preview` first: projection trades samples for SNPs — if the retained-SNP count collapses at your projection, lower it. Populations with few individuals cap the joint projection.

**fastsimcoal2 anti-hang / anti-crash rules (non-negotiable):**

1. Time flows backward in coalescent models: expansion times (TEXP) must be **smaller** than every divergence time (TDIV). TEXP > any TDIV = infinite hang.
2. All time ranges must be non-overlapping; keep them realistic (e.g. TEXP 800–1400, TDIV 2000–6000 for recent human-scale history).
3. No time values > 10,000 generations — known to segfault fsc28.
4. Migration rates: `logunif 1e-5 5e-4`, never above 0.01.
5. Parameter names must never be substrings of each other (`NANC` vs `NANC12` silently corrupts substitution). Use clearly distinct names: `NPOP0`, `ANC`, `TDIV12`. Common convention: current populations plain, ancestral sizes `ANC*`.
6. `[COMPLEX PARAMETERS]` comes after `[PARAMETERS]`; dummy/derived parameters are declared like `0 NAME unif 0 0 hide`.
7. No `[RULES]` section for fsc28.
8. Verify the final grammar against the fsc28 PDF manual of the installed version when in doubt — the parser is unforgiving.

**Single-population prior-setting from SFS summaries** (data-driven ranges):

- Estimate Ne ≈ π / (4 × 2.5e-8); set its range to [max(1000, 0.1·Ne), min(100000, 10·Ne)].
- From the Tajima's-D-like signal of the SFS:

| Signal | Interpretation | TEXP range | RESIZE range |
|---|---|---|---|
| D < −1.5 | recent rapid expansion | 50–5000 | 2.0–50.0 |
| −1.5 … −0.5 | moderate expansion | 100–10000 | 1.5–20.0 |
| D > 1.0 | bottleneck / balancing selection | 500–20000 | 0.1–2.0 |
| otherwise | roughly stable | 200–15000 | 0.5–5.0 |

**Likelihood-driven model search** (iterate, don't one-shot):

- Best likelihood still poor for the panel scale (e.g. > −30000): try a **simpler** model.
- Improvement between rounds < ~500 log units: make **more dramatic** parameter changes.
- MLE sits on a range boundary: **expand the range** in that direction and rerun.
- Compare candidate models by AIC = 2k − 2·lnL (k = estimated parameters), from each model's best replicate.

## Output verification checklist

- Per replicate: `PREFIX/PREFIX.bestlhoods` (likelihoods: MaxEstLhood vs MaxObsLhood — a large gap means the model fits poorly) and `PREFIX/PREFIX.maxlhood` (MLE parameter values).
- No MLE value pinned on a prior boundary (if so, see search rules).
- The `.obs` file matched the expected basename (fsc28 hangs or exits immediately otherwise) — remove it from the run directory afterward to keep runs isolated.
- All replicates used identical `.tpl/.est`; only seeds differ.

## Figure reading guide

- Plot the observed vs expected SFS from the best run (`PREFIX_bestYobs`-style outputs in the run directory): systematic residuals at rare or common bins point at model misfit.
- For the final model, export to Demes (below) and draw the demographic graph with `demesdraw` (Python) — a model diagram communicates sizes/times better than a parameter table.

## Demes export

Convert the MLE point estimates into a Demes YAML for sharing and downstream reuse (demes-spec format; validate with the `demes` Python package):

```yaml
description: Two-population divergence inferred with fastsimcoal2
time_units: generations
demes:
  - name: ANC
    epochs:
      - {end_time: TDIV_EST, start_size: ANC_EST}
  - name: POP0
    ancestors: [ANC]
    epochs:
      - {end_time: 0, start_size: NPOP0_EST}
  - name: POP1
    ancestors: [ANC]
    epochs:
      - {end_time: 0, start_size: NPOP1_EST}
migrations:
  - {demes: [POP0, POP1], rate: MIG_EST}
```

## Common pitfalls

- TEXP > TDIV, overlapping time ranges, or times > 10,000 generations → hang/segfault (rules 1–3).
- Substring parameter names (rule 5) → silent mis-substitution; results look fine but are wrong.
- Folded/unfolded mismatch: `-m` (MAF) with a folded easySFS spectrum vs `-d` with polarized data — mixing them invalidates everything.
- Reporting the first run as the answer instead of the best of many replicates.
- Projecting the SFS so aggressively that only a few hundred SNPs remain → jittery likelihoods and unstable MLEs.
