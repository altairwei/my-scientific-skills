#!/usr/bin/env bash
# scientific-writing/figure-style/scripts/setup.sh
# Idempotent setup for the figure-style skill. The helper module is
# import-only — the deps (matplotlib/numpy, scipy for ci95) are supplied by
# the caller's `uv run --with ...`. This script just makes sure `uv` exists
# and warms the wheel cache so the first plotting run is fast/offline.
# Safe to re-run; never blocks.

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

# ── warm the dep cache (best-effort) ─────────────────────────────────────────
SCRIPT_DIR="$(dirname "$(realpath "$0")")"
say "warming matplotlib/numpy/scipy into the uv cache"
if uv run --with matplotlib --with numpy --with scipy python -c "
import sys; sys.path.insert(0, '$SCRIPT_DIR')
import figure_style
print('figure_style import OK —', len([n for n in dir(figure_style) if not n.startswith('_')]), 'public names')
"; then
    say "deps warmed — the first uv run --with matplotlib ... call will be fast / offline"
else
    warn "dep warm failed (offline?) — uv run will retry on first use; not fatal."
fi

say "figure-style ready. Usage:"
say "  sys.path.insert(0, '$SCRIPT_DIR'); import figure_style as fs"
