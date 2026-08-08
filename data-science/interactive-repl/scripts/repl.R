#!/usr/bin/env Rscript
# data-science/interactive-repl/scripts/repl.R
# Persistent R namespace over a JSON-per-line TCP (localhost) protocol.
#
# The server (repl_server.py) listens on a TCP port; R connects as a client and
# runs an eval loop. (R's base socketConnection is TCP-only — no Unix domain
# sockets — so we use TCP localhost on an ephemeral port the server passes.)
#
# PROTOCOL STATE LIVES IN A PROTECTED .repl ENV (dot-prefixed → hidden from ls(),
# and out of the bare-name slot so user code like `con <- DBI::dbConnect(...)` can't
# clobber the socket — the r-cell lesson, where the protocol lived in tmux/bash,
# not in an R variable user code could touch). User code evals in globalenv() —
# clean. Neutralized helpers (dt_table → kable) are ATTACHED on the search path as a
# FALLBACK: the user's own dt_table wins; rm("dt_table") removes the user's and falls
# back to the worker version. ls(.GlobalEnv) lists user objects only.
#
# Env: REPL_PORT = the server's TCP port (required).
# Eval logic adapted from external/r-cell/r-cell.sh's _build_wrapper (withVisible +
# eval in globalenv, ggsave on ggplot, tryCatch guarantees the response always
# returns). Neutralizes interactive R functions that block/error headless.

.repl <- new.env(parent = emptyenv())
.repl$port <- as.integer(Sys.getenv("REPL_PORT", "0"))
if (is.na(.repl$port) || .repl$port <= 0) stop("REPL_PORT env var must be set to the server's TCP port")
# Slurm mode: REPL_HOST is the login node as seen from the compute node
# (default "localhost" = local mode). Direct transport connects straight
# across the interconnect; the tunnel branch (REPL_TRANSPORT=tunnel) is
# implemented in the same place — see the `if` below.
.repl$host <- Sys.getenv("REPL_HOST", "localhost")
.repl$con <- NULL
if (identical(Sys.getenv("REPL_TRANSPORT"), "tunnel")) {
  # Tunnel mode: ssh -fN -L <L>:localhost:<port> <host> forwards the server's
  # listener to this (compute) node. Base R cannot read an OS-assigned
  # port=0, so probe a random high port; system2(wait=TRUE) returns the ssh
  # exit status — with -f the foreground exits quickly either way, so 0 means
  # the tunnel is up (bind collision / auth failure → non-zero → retry).
  for (i in 1:5) {
    L <- 20000 + sample(20000, 1)
    # Probe with a CLIENT connection, not server=TRUE (R's server sockets
    # fail on some builds — "problem in listening on this socket"): a
    # connection to a free port is refused (error → free); one to a taken
    # port succeeds (→ taken). The tiny probe/ssh-bind race is covered by
    # ssh's ExitOnForwardFailure and the retry loop.
    probe <- tryCatch({
      c <- suppressWarnings(socketConnection(host = "localhost", port = L,
                                             server = FALSE, blocking = TRUE,
                                             open = "r+b", timeout = 2))
      close(c)
      FALSE
    }, error = function(e) TRUE)
    if (!probe) next
    st <- system2("ssh", c("-fN", "-L", sprintf("%d:localhost:%d", L, .repl$port),
                           .repl$host, "-o", "BatchMode=yes",
                           "-o", "ExitOnForwardFailure=yes",
                           "-o", "ServerAliveInterval=30",
                           "-o", "ConnectTimeout=10"), wait = TRUE)
    if (st != 0) next
    .repl$con <- socketConnection(host = "localhost", port = L, server = FALSE,
                                  blocking = TRUE, open = "r+b", timeout = 86400L)
    break
  }
  if (is.null(.repl$con)) {
    stop("ssh -L tunnel to ", .repl$host, " failed (check passwordless ssh)")
  }
} else {
  .repl$con <- socketConnection(host = .repl$host, port = .repl$port, server = FALSE,
                                blocking = TRUE, open = "r+b", timeout = 86400L)
}
on.exit(close(.repl$con))
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
  cat(jsonlite::toJSON(obj, auto_unbox = TRUE, null = "null"), "\n", sep = "", file = .repl$con)
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
  out <- ""; plots <- character(0)
  stdout_con <- textConnection("out", "w", local = TRUE)
  sink(stdout_con, type = "output")
  error_msg <- tryCatch({
    ex <- parse(text = code)
    for (i in seq_along(ex)) {
      r <- withVisible(eval(ex[[i]], envir = globalenv()))
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
  list(stdout = out_text, stderr = "", error = error_msg, plots = as.list(plots),
       truncated = FALSE, degraded = FALSE)
}

# Ready marker: token (validated by the server in slurm mode) + SLURM job info.
.repl$write_json(list(ready = TRUE, token = Sys.getenv("REPL_TOKEN", ""),
                      job_id = Sys.getenv("SLURM_JOB_ID"),
                      node = Sys.getenv("SLURM_JOB_NODELIST")))

# Main loop inside a function so req/res/rid/line are not exposed in globalenv (else
# list_variables would leak them). .repl (dot-prefixed, in globalenv) is reachable as
# the function's enclosing env.
.repl$run_loop <- function() {
  repeat {
    line <- tryCatch(readLines(.repl$con, n = 1),
                     error = function(e) character(0),
                     warning = function(w) character(0))
    if (length(line) == 0) break  # EOF / connection closed
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
