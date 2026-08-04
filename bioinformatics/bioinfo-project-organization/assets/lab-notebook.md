# Lab Notebook

Chronological log of the project. Append a new entry for every experiment —
failed ones too. Adapt the section headers to your project; the point is that
a stranger can read this and understand what was done, why, and what the
result was.

## 2026-08-04

- **What:** ran the motif scan over the curated FASTA set with the new
  background model.
- **Why:** the previous scan used a uniform background and over-called
  AT-rich regions; the new model corrects for genomic composition.
- **Observed:** 312 significant motifs (FDR < 0.05), down from 487 — the
  AT-rich false positives collapsed as expected. The top hit is still SOX2.
- **Conclusion:** the new background is an improvement; reuse it for
  downstream scans.
- **Next:** rerun the enrichment analysis against the filtered motif set;
  compare to the ChIP-seq peak overlap.
- **Failed:** none today. (When something fails, record *how you know* it
  failed — e.g. "all p-values were uniform, indicating the permutation test
  never ran on the shuffled control".)

<!-- Link key outputs:
     experiments/2026-08-04/results/top_motifs.tsv
     artifacts/model_newbg.h5 -->
