#!/usr/bin/env bash
# data-science/interactive-repl/scripts/setup.sh
# One-shot dependency installer for the interactive-repl skill.
#
# Installs everything the MCP server + workers need so sessions start
# without mid-session downloads (bad networks: run once when the network is
# good, everything after works from uv's wheel cache). Idempotent — safe to
# re-run anytime; run it as the first step of any setup/troubleshooting.
#
#   scripts/setup.sh                   # check + install what's missing; report status
#   scripts/setup.sh --r               # also install the R packages (jsonlite,
#                                      #   knitr, ggplot2) — heavy, opt-in
#   CLAUDE_PLUGIN_DATA=... setup.sh    # install into a custom data dir (HPC:
#                                      #   point at SHARED storage, see SKILL.md)
#
# Exit code 0 = python side fully ready; R status is reported separately.
#
# Note: py-site wheels are python-version-specific (uv builds them for the
# same interpreter the servers' `uv run` uses, so they match by default).
# Re-run this script if that interpreter ever changes.
set -euo pipefail

SITE_DIR="${CLAUDE_PLUGIN_DATA:-/tmp/interactive-repl-data}/py-site"
PY_DEPS=(mcp pydantic numpy pandas matplotlib)
R_PKGS=(jsonlite knitr ggplot2)
R_REPO="https://cloud.r-project.org"
R_STATUS="missing"

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mXX\033[0m %s\n' "$*" >&2; exit 1; }

# --- 1/4 uv -------------------------------------------------------------
say "1/4  uv"
if command -v uv >/dev/null 2>&1; then
    uv --version
else
    say "uv not found — installing to ~/.local/bin/uv"
    if curl -LsSf https://astral.sh/uv/install.sh | sh; then
        export PATH="$HOME/.local/bin:$PATH"
        command -v uv >/dev/null 2>&1 || die "uv installed but not on PATH — restart your shell, then re-run this script"
    else
        die "uv install failed (network?) — retry: curl -LsSf https://astral.sh/uv/install.sh | sh"
    fi
fi

# --- 2/4 python runtime deps --------------------------------------------
# One uv pip install --target covers everything the server (mcp, pydantic)
# and the worker (numpy, pandas, matplotlib) need — no per-package lazy
# installs at session time. Wheels land in ~/.cache/uv, so the server's uv
# run ephemeral env builds offline afterwards.
say "2/4  python runtime deps -> $SITE_DIR"
mkdir -p "$SITE_DIR"
if ! uv pip install --target "$SITE_DIR" "${PY_DEPS[@]}"; then
    warn "network install failed — retrying from uv's wheel cache (--offline)"
    uv pip install --offline --target "$SITE_DIR" "${PY_DEPS[@]}" || \
        die "could not install python deps even from cache — re-run this script when the network is available"
fi

# --- 3/4 R --------------------------------------------------------------
say "3/4  R"
if command -v Rscript >/dev/null 2>&1; then
    Rscript --version 2>&1 | head -1
    missing=$(
        Rscript -e 'cat(paste(setdiff(c("jsonlite","knitr","ggplot2"), rownames(installed.packages())), collapse=" "))'
    )
    if [ -n "$missing" ]; then
        warn "R packages missing: $missing"
        R_STATUS="R found, missing packages: $missing"
        if [ "${1:-}" = "--r" ]; then
            say "installing R packages: ${R_PKGS[*]} (repos=$R_REPO)"
            pkgs=$(printf '"%s",' "${R_PKGS[@]}" | sed 's/,$//')
            Rscript -e "install.packages(c($pkgs), repos='$R_REPO')" || die "R package install failed"
            R_STATUS="ready"
        else
            warn "re-run with --r to install them, or install via conda/module (see references/r-setup.md)"
        fi
    else
        say "R packages ok: jsonlite knitr ggplot2"
        R_STATUS="ready"
    fi
else
    warn "Rscript not on PATH — R sessions cannot start until R is installed."
    warn "Run scripts/discover.py to scan conda envs / system dirs for R, or see references/r-setup.md."
fi

# --- 4/4 summary ---------------------------------------------------------
say "4/4  status"
echo "  py: ready — deps in $SITE_DIR, uv wheel cache warm"
echo "  r: $R_STATUS"
echo ""
echo "Next (only if the MCP tools are missing from the agent's toolset):"
echo "  /plugin install data-science@my-scientific-skills   # if not installed"
echo "  /reload-plugins  (or restart Claude Code — MCP servers load once per process)"
