---
name: exploratory-data-analysis
description: Guides Claude through a structured exploratory data analysis (EDA) of a tabular dataset — profiling columns, checking data quality, visualizing distributions and relationships, and summarizing findings. Use this skill whenever the user shares a CSV/TSV/Excel/parquet file and asks to "explore", "look at", "summarize", "profile", or "understand" the data, even if they never say "EDA".
metadata:
  author: Altair Wei
  version: "1.0"
license: MIT
---

# Exploratory Data Analysis

Turn an unfamiliar dataset into a clear picture of what it contains, what is wrong with it, and what is worth analyzing — before any modeling happens. Skipping EDA is how subtle data problems (duplicated rows, sentinel values, unit mix-ups) silently corrupt downstream results, so be thorough here even when the user is in a hurry.

## Process

### 1. Identify the data and the question

Find the dataset the user means (ask if ambiguous) and load it with pandas (Python) or tidyverse (R) — match the language of the surrounding project. Note the user's stated goal: it decides which columns and relationships deserve the most attention later.

### 2. Profile the structure

Report the shape, column names, dtypes, and a head/tail sample. Then profile each column:

- **Numeric**: count, mean, sd, min/max, quartiles, skew.
- **Categorical**: number of levels, top frequencies, rare levels.
- **Datetime**: range, gaps, timezone issues.

Flag columns whose inferred dtype looks wrong (numbers stored as strings, dates as integers) — parsing bugs here propagate everywhere.

### 3. Audit data quality

Check explicitly, and report each finding with concrete numbers:

- Missing values per column (count and percent), and whether missingness correlates with other columns.
- Exact duplicate rows; near-duplicates on key columns.
- Impossible or sentinel values (negative ages, 999/−1 placeholders, dates in the future).
- Outliers — via IQR or z-score, but judge them against domain plausibility, not just statistics.

Do **not** silently clean anything yet. The user needs to know what is wrong before deciding what to drop or fix; some "errors" are real phenomena.

### 4. Visualize

Prefer a small number of informative plots over many decorative ones:

- Distributions of key numeric columns (histograms).
- Counts of important categoricals (bar plots).
- Pairwise relationships relevant to the user's question (scatter, boxplot by group, correlation heatmap for numeric sets).

Label axes with units where known. Save plots to files if the session is non-interactive so the user can open them.

### 5. Summarize findings

End with a short written summary in this structure:

1. **What the data is** — rows, columns, what a row represents.
2. **Quality issues found** — each with counts and affected columns.
3. **Notable patterns** — distributions, relationships, surprises.
4. **Recommended next steps** — cleaning decisions to confirm, analyses that look promising.

## Rules

- Show the actual numbers and plots; never claim a finding you did not compute.
- Keep raw data immutable: do cleaning on a copy or in a clearly separate step.
- If the dataset is too large to load, sample it and say so.
- When something looks like an error but could be real (a huge outlier, a strange category), surface it as a question rather than deciding alone.
