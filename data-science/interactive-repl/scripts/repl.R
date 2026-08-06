#!/usr/bin/env Rscript
# data-science/interactive-repl/scripts/repl.R
# Persistent R namespace over a JSON-per-line TCP (localhost) protocol.
#
# The server (r_repl_server.py) listens on a TCP port; R connects as a client and
# runs an eval loop. (R's base socketConnection is TCP-only — no Unix domain
# sockets — so we use TCP localhost on an ephemeral port the server passes.)
#
# Env: REPL_PORT = the server's TCP port (required).
# Eval logic adapted from external/r-cell/r-cell.sh's _build_wrapper (withVisible +
# eval in globalenv, ggsave on ggplot, tryCatch guarantees the response always
# returns). Neutralizes interactive R functions that block/error headless.

port <- as.integer(Sys.getenv("REPL_PORT", "0"))
if (is.na(port) || port <= 0) stop("REPL_PORT env var must be set to the server's TCP port")

con <- socketConnection(host = "localhost", port = port, server = FALSE,
                        blocking = TRUE, open = "r+b", timeout = 86400L)
on.exit(close(con))

options(width = 400)  # wide so captured R lines don't wrap in the response

`%||%` <- function(a, b) if (is.null(a) || length(a) == 0) b else a

write_json <- function(obj) {
  cat(jsonlite::toJSON(obj, auto_unbox = TRUE, null = "null"), "\n", sep = "", file = con)
}

run_cell <- function(code) {
  out <- ""; plots <- character(0)
  stdout_con <- textConnection("out", "w", local = TRUE)
  sink(stdout_con, type = "output")
  error_msg <- tryCatch({
    ex <- parse(text = code)
    for (i in seq_along(ex)) {
      r <- withVisible(eval(ex[[i]], envir = globalenv()))
      if (isTRUE(r$visible)) {
        if (inherits(r$value, "ggplot")) {
          f <- tempfile(fileext = ".png")
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
  list(stdout = out_text, stderr = "", error = error_msg, plots = plots,
       truncated = FALSE, degraded = FALSE)
}

# Neutralize interactive R functions that open a browser/widget and block/error
# in a headless session (r-cell lesson). dt_table (a DT htmlwidget) → plain kable.
dt_table <- function(df, digits = NULL, caption = NULL, ...) {
  if (!is.null(caption)) cat("## ", caption, "\n", sep = "")
  print(knitr::kable(df))
}
assign("dt_table", dt_table, envir = globalenv())

# Ready marker on the protocol channel.
write_json(list(ready = TRUE))

repeat {
  line <- tryCatch(readLines(con, n = 1),
                   error = function(e) character(0),
                   warning = function(w) character(0))
  if (length(line) == 0) break  # EOF / connection closed
  line <- line[nzchar(line)]
  if (length(line) == 0) next
  req <- tryCatch(jsonlite::fromJSON(line), error = function(e) NULL)
  if (is.null(req)) {
    write_json(list(id = "unknown", stdout = "", stderr = "", error = "Invalid JSON",
                    plots = character(0), truncated = FALSE, degraded = FALSE))
    next
  }
  rid <- req$id %||% "unknown"
  res <- tryCatch(run_cell(req$code), error = function(e) {
    list(stdout = "", stderr = "", error = conditionMessage(e),
         plots = character(0), truncated = FALSE, degraded = FALSE)
  })
  res$id <- rid
  write_json(res)
}
