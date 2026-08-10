# Heritability and Genetic Correlation: GCTA-GREML and LDSC

Load when the user wants to estimate SNP heritability, genetic correlation between traits, partitioned/cell-type heritability, or to interpret what heritability estimates mean.

## Table of contents

- [Concepts](#concepts)
- [GCTA-GREML (individual-level genotypes)](#gcta-greml-individual-level-genotypes)
- [LDSC (summary statistics only)](#ldsc-summary-statistics-only)
- [Choosing GREML vs LDSC](#choosing-greml-vs-ldsc)

## Concepts

- **Broad-sense heritability** H² = Var(G)/Var(P): all genetic effects (additive + dominance + epistasis).
- **Narrow-sense heritability** h² = Var(A)/Var(P): additive genetic effects only — what most GWAS methods estimate.
- **SNP heritability** h²_SNP: variance explained by *measured SNPs*, typically ≪ h² from family studies — the gap is the "missing heritability" (unmeasured variants, rare variants, non-additive effects).
- **Liability-scale conversion** (binary traits): h²_liability = h²_observed · K(1−K)/[z² · K(1−K)/(P(1−P))] — where K is population prevalence, P the sample case fraction, z the liability density at the threshold. Always report which scale you used.
- **Genetic correlation** r_g = ρ_g / √(h²₁·h²₂): correlation of additive effects across traits, estimated on the liability or observed scale for binary traits.

## GCTA-GREML (individual-level genotypes)

GREML fits y = Xβ + g + e, Var(y) = A·σ²_g + I·σ²_e with GRM A = WW′/N from LD-pruned common SNPs. Needs **individual genotypes** (not sumstats) and recommends > 4000 unrelated samples.

```bash
# Step 1: GRM from LD-pruned SNPs
gcta --bfile sample_data.clean --extract qc.prune.in --autosome --maf 0.01 \
     --make-grm --out 1kg_eas

# Step 2: REML variance components, with PCs as fixed effects and prevalence
# for liability-scale conversion of a binary trait
awk '{print $1,$2,$5,$6,$7,$8,$9}' pca.sscore > 5PCs.txt
gcta --grm 1kg_eas --pheno pheno.txt --prevalence 0.5 \
     --qcovar 5PCs.txt --reml --out 1kg_eas
```

- Read `1kg_eas.hsq`: `V(G)/Vp` is h²_SNP; with `--prevalence` it also reports the liability-scale estimate. Check SEs — h² with a huge SE is not a finding.
- GREML is sensitive to sample composition: relatives inflate it; restrict to unrelated samples (KING cutoff 0.0884) before building the GRM.
- LD-pruned, common SNPs only: MAF > 0.01, r²-pruned (e.g. `--indep-pairwise 50 5 0.2`).

## LDSC (summary statistics only)

LD score regression exploits E[χ² | l_j] = N·h²·l_j/M + N·a + 1, where l_j is the LD score of variant j (its total r² with other variants). The slope gives h², the intercept diagnoses inflation (stratification/relatedness), and cross-trait regression gives r_g — all from sumstats + an LD reference panel.

```bash
# 1. Munge: format + restrict to HapMap3 SNPs
python munge_sumstats.py --sumstats study.txt.gz \
    --merge-alleles w_hm3.snplist \
    --a1 ALT --a2 REF --chunksize 500000 --out munged

# 2. Univariate heritability
python ldsc.py --h2 munged.sumstats.gz \
    --ref-ld-chr eas_ldscores/ --w-ld-chr eas_ldscores/ --out h2

# 3. Cross-trait genetic correlation
python ldsc.py --rg trait1.sumstats.gz,trait2.sumstats.gz \
    --ref-ld-chr eas_ldscores/ --w-ld-chr eas_ldscores/ --out rg
```

- **Read the intercept and ratio:** intercept ≈ 1.0 (no inflation) and ratio = (intercept−1)/(mean(χ²)−1) ≈ 0 (10–20% is common and tolerable). λ_GC alone cannot distinguish inflation from polygenicity; LDSC's intercept can.
- h² is reported on the observed scale; convert to liability with the case fraction if binary (LDSC has `--samp-prev`/`--pop-prev`).
- Partitioned heritability (`--h2` with baseline-LD annotations) attributes h² to functional categories; `--h2-cts` (LDSC-SEG) tests cell-type/tissue enrichment — both need precomputed annotation LD scores.
- Ancestry-matched LD reference is essential (see sumstats-basics); EUR/EAS panels ship precomputed LD scores.

## Choosing GREML vs LDSC

| | GREML | LDSC |
|---|---|---|
| Input | genotypes | sumstats |
| h² accuracy | higher per-cohort | slightly noisier, no sample overlap issues |
| Cross-trait rg | needs same-sample genotypes | works across studies (even different cohorts) |
| Partitioned/cts | not standard | yes |
| Cost | heavy (GRM + REML) | light |

Default: GREML when genotypes are available and the question is "how much of this trait's variance"; LDSC when only sumstats exist or the question involves multiple studies/annotations. Report h² ± SE on both observed and liability scales for binary traits.
