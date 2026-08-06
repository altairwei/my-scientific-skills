# Base interactive-repl R sidecar — auto-sourced into every r-repl session.
# Definition-only, lazy deps — reference example for sidecar authoring.

who <- function() {
  ns <- ls(envir = .GlobalEnv)
  cls <- vapply(ns, function(nm) class(get(nm, envir = .GlobalEnv))[1], character(1))
  print(data.frame(object = ns, class = cls, row.names = NULL))
}

peek <- function(obj) {
  if (is.data.frame(obj)) {
    cat(sprintf("data.frame %s\n", paste(dim(obj), collapse = " x ")))
    print(str(obj)); print(head(obj))
  } else if (is.recursive(obj)) {
    cat(sprintf("%s len=%d\n", class(obj)[1], length(obj)))
    print(str(obj, max.level = 1))
  } else {
    print(obj)
  }
}

fig <- function(n = 1) {
  pdir <- file.path(Sys.getenv("CLAUDE_PLUGIN_DATA", "/tmp/interactive-repl-data"), "plots")
  fs <- list.files(pdir, pattern = "^fig.*\\.png$", full.names = TRUE)
  fs <- sort(fs)
  if (length(fs) >= n) fs[n] else NULL
}
