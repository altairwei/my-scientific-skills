#!/usr/bin/env bash
# scientific-writing/literature-review/scripts/setup.sh
# Idempotent setup for the literature-review skill. The CLI is stdlib-only
# (urllib/json/re/time) — no third-party deps, no env-var config. This just
# makes sure `uv` exists. Safe to re-run; never blocks.

set -euo pipefail

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }

# ── uv ───────────────────────────────────────────────────────────────────────
if command -v uv >/dev/null 2>&1; then
    say "uv present: $(uv --version)"
else
    say "uv not found — installing via the official installer"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck disable=SC1091
    source "$HOME/.local/bin/env" 2>/dev/null || true
    if ! command -v uv >/dev/null 2>&1; then
        warn "uv still not on PATH after install — restart your shell (or add ~/.local/bin to PATH), then re-run."
        exit 1
    fi
    say "uv installed: $(uv --version)"
fi

# ── status ───────────────────────────────────────────────────────────────────
say "literature-review ready (stdlib-only, no deps). Try:"
say "  uv run $(dirname "$(realpath "$0")")/literature_review.py --help"
