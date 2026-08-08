# R setup — interactive-repl

## Finding R on HPC

On HPC login nodes R is usually NOT on PATH — it lives in a conda env or a
module. The fastest route: run the skill's scanner —
**`scripts/discover.py`** — which scans PATH, conda envs (`conda env list
--json`, falling back to `~/.conda/environments.txt`), uv-managed pythons and
system dirs (`/opt/R`, `/usr/lib/R`, …), probes every candidate's version and
the packages this skill needs, and prints a READY-marked report with the exact
`INTERACTIVE_REPL_R_ENV` / `INTERACTIVE_REPL_R_BIN` lines to use. Manual
commands below if you want to look yourself:

```bash
command -v Rscript                       # on PATH already?
conda env list                           # conda envs present?
conda run -n <env> Rscript --version     # test each candidate env
module avail 2>&1 | grep -i r            # or an R module: module load R
```

Then check the required packages (jsonlite is REQUIRED; knitr + ggplot2 for
dt_table/plot capture):

```bash
conda run -n <env> Rscript -e 'cat(rownames(installed.packages()), sep="\n")' | grep -E '^(jsonlite|knitr|ggplot2)$'
```

Configure the server (persist in `~/.bashrc` so every Claude Code launch picks
it up — the server reads these env vars at launch):

```bash
export INTERACTIVE_REPL_R_ENV=<env>      # conda env name
# or
export INTERACTIVE_REPL_R_BIN=/path/to/R # explicit binary
```

If no env has R, create one (conda-forge has all three packages, no
compilation):

```bash
mamba create -n r-env -c conda-forge r-base r-jsonlite r-knitr r-ggplot2
export INTERACTIVE_REPL_R_ENV=r-env
```

The one-shot installer `scripts/setup.sh` checks the R on PATH (and with `--r`
installs the packages) — but on HPC you still need to point the server at the
right env via the env vars above.

## R + packages

An `r:` session spawns `R --no-save --no-restore` running `scripts/repl.R`. It
requires:

- **R** on PATH (or set `INTERACTIVE_REPL_R_BIN` to the R binary path).
- **jsonlite** (required — the worker's JSON protocol). Install:
  `install.packages("jsonlite", repos="https://cloud.r-project.org")`.
- **knitr** + **ggplot2** (for `dt_table`→`kable` neutralization and `ggsave` plot
  capture). Without them the worker still runs; `dt_table` will error and ggplot
  objects won't auto-save.

If the system R library isn't writable, install to the user library (R auto-uses
`R_LIBS_USER` once the dir exists):

```r
install.packages(c("jsonlite", "knitr", "ggplot2"),
                 lib = Sys.getenv("R_LIBS_USER"),
                 repos = "https://cloud.r-project.org")
```

## Conda env

If R lives in a conda env, set `INTERACTIVE_REPL_R_ENV` (the server wraps the launch in
`conda run -n <env> --no-capture-output`). Set per-project via `.claude/settings.json`
`env` or your shell env.

## Conventions

- **`pkg::fun()` over `library()`.** The project forbids `library()` — it attaches and
  can clobber. Always namespace: `dplyr::mutate()`, `ggplot2::ggplot()`.
- **`scale_y_sqrt()` over `scale_y_log10()`.** A `scale_y_log10()` histogram with any
  `count=1` bin shows a down-fill artifact (the bar renders from y=1 toward the axis
  limit). `scale_y_sqrt()` has no such artifact (`sqrt(0)=0`). See `plot-iteration.md`.
- **Absolute paths** for `source()`/`read.csv()`/file args — the session's cwd may
  differ from the agent's.

## Neutralized interactive functions

The worker overrides `dt_table` (a DT htmlwidget whose print method opens a browser —
which blocks/errors headless) to print `knitr::kable()` instead. This is re-applied at
session start. If your project has other interactive-only functions (e.g. `view()`,
`DT::datatable()` direct calls), add overrides in your skill's `kernel.R` sidecar.

## Notebook/qmd chunk extraction

To run a labeled chunk from a `.qmd`/`.Rmd`, extract its body via `knitr::purl` (the
standard tangler) and pass the code to `run_code`:

```r
tmp <- tempfile(fileext = ".R")
knitr::purl("doc.qmd", output = tmp, documentation = 1)
# read the chunk by label from the tangled file, then run_code it
```

A built-in labeled-chunk tool is deferred to v2 — for now, extract and pass the code.
