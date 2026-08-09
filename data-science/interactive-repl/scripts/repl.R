#!/usr/bin/env Rscript
# data-science/interactive-repl/scripts/repl.R
# Persistent R namespace over a JSON-per-line stdio protocol.
#
# Requests arrive on stdin (readLines(.repl$con_in, n=1) — blocks on the pipe,
# EOF → character(0) → exit); responses go to stdout via cat(file="") +
# flush(stdout()). The per-cell sink(type="output") window never overlaps
# protocol writes, so responses cannot be captured. Warnings are collected
# with withCallingHandlers (muffled, execution continues) and surface in the
# response's stderr field; R's message sink is NOT usable here — it also
# captures stderr() writes and dies silently (verified 2026-08-09). User
# system()/child-process output leaks raw lines onto stdout — the server's
# tolerant reader skips non-JSON lines.
#
# PROTOCOL STATE LIVES IN A PROTECTED .repl ENV (dot-prefixed → hidden from ls(),
# and out of the bare-name slot so user code can't clobber it). User code evals
# in globalenv() — clean. Neutralized helpers (dt_table → kable) are ATTACHED on
# the search path as a FALLBACK: the user's own dt_table wins; rm("dt_table")
# removes the user's and falls back to the worker version. ls(.GlobalEnv)
# lists user objects only.
#
# Env: none required — SLURM_JOB_ID / SLURM_JOB_NODELIST (set by srun) are read
# for the ready marker so session_info can report the job.
# Eval logic adapted from external/r-cell/r-cell.sh's _build_wrapper (withVisible
# + eval in globalenv, ggsave on ggplot, tryCatch guarantees the response always
# returns). Neutralizes interactive R functions that block/error headless.

.repl <- new.env(parent = emptyenv())
.repl$con_in <- file("stdin", "r")
options(width = 400)  # wide so captured R lines don't wrap in the response

.repl$plot_dir <- function() {
  d <- file.path(Sys.getenv("CLAUDE_PLUGIN_DATA", "/tmp/interactive-repl-data"), "plots")
  dir.create(d, recursive = TRUE, showWarnings = FALSE)
  d
}

# plots is wrapped in as.list() on the way out so a length-1 character vector
# serializes as a JSON array ["..."], not a scalar "..." — the server's
# RunResult.plots is list[str], and a scalar string fails pydantic validation.
.repl$write_json <- function(obj) {
  cat(jsonlite::toJSON(obj, auto_unbox = TRUE, null = "null"), "\n", sep = "", file = "")
  flush(stdout())
}

.repl$dt_table_impl <- function(df, digits = NULL, caption = NULL, ...) {
  if (!is.null(caption)) cat("## ", caption, "\n", sep = "")
  print(knitr::kable(df))
}

# Attach the neutralized dt_table on the search path as a FALLBACK (below globalenv):
# a user's own `dt_table <- ...` shadows this; rm("dt_table") removes the user's, then
# this is used again. Not listed by ls(.GlobalEnv). (r-cell lesson: DT htmlwidgets open
# a browser and block/error headless; the kable version is a safe fallback.)
attach(list(dt_table = .repl$dt_table_impl), name = "interactive-repl:helpers",
       warn.conflicts = FALSE)
on.exit(detach("interactive-repl:helpers"), add = TRUE)

.repl$run_cell <- function(code) {
  out <- ""; plots <- character(0); warns <- character(0)
  stdout_con <- textConnection("out", "w", local = TRUE)
  sink(stdout_con, type = "output")
  error_msg <- tryCatch({
    ex <- parse(text = code)
    for (i in seq_along(ex)) {
      r <- withCallingHandlers(
        withVisible(eval(ex[[i]], envir = globalenv())),
        warning = function(w) {
          warns <<- c(warns, conditionMessage(w))
          invokeRestart("muffleWarning")
        }
      )
      if (isTRUE(r$visible)) {
        if (inherits(r$value, "ggplot")) {
          f <- tempfile(pattern = "fig-", fileext = ".png", tmpdir = .repl$plot_dir())
          tryCatch(ggplot2::ggsave(f, r$value, width = 12, height = 8, dpi = 110),
                   error = function(e) NULL)
          plots <- c(plots, f)
          cat("FIGURE saved:", f, "\n")
        } else {
          print(r$value)
        }
      }
    }
    NULL
  }, error = function(e) conditionMessage(e))
  sink(); close(stdout_con)
  out_text <- paste(out, collapse = "\n")  # character(0) → "" (nzchar-safe)
  if (!nzchar(out_text) && !is.null(error_msg)) out_text <- paste0("ERROR: ", error_msg)
  list(stdout = out_text, stderr = paste(warns, collapse = "\n"),
       error = error_msg, plots = as.list(plots),
       truncated = FALSE, degraded = FALSE)
}

# Ready marker: job info from srun's env (read by the server over stdout).
.repl$write_json(list(ready = TRUE,
                      job_id = Sys.getenv("SLURM_JOB_ID"),
                      node = Sys.getenv("SLURM_JOB_NODELIST")))

# Main loop inside a function so req/res/rid/line are not exposed in globalenv (else
# list_variables would leak them). .repl (dot-prefixed, in globalenv) is reachable as
# the function's enclosing env.
.repl$run_loop <- function() {
  repeat {
    line <- tryCatch(readLines(.repl$con_in, n = 1),
                     error = function(e) character(0),
                     warning = function(w) character(0))
    if (length(line) == 0) break  # EOF / stdin closed
    line <- line[nzchar(line)]
    if (length(line) == 0) next
    req <- tryCatch(jsonlite::fromJSON(line), error = function(e) NULL)
    if (is.null(req)) {
      .repl$write_json(list(id = "unknown", stdout = "", stderr = "", error = "Invalid JSON",
                            plots = as.list(character(0)), truncated = FALSE, degraded = FALSE))
      next
    }
    rid <- if (is.null(req$id) || length(req$id) == 0) "unknown" else req$id
    res <- tryCatch(.repl$run_cell(req$code), error = function(e) {
      list(stdout = "", stderr = "", error = conditionMessage(e),
           plots = as.list(character(0)), truncated = FALSE, degraded = FALSE)
    })
    res$id <- rid
    .repl$write_json(res)
  }
}
.repl$run_loop()
