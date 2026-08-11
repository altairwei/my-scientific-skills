#!/usr/bin/env bash
# scientific-writing/figure-composer/scripts/setup.sh
# Idempotent setup for the figure-composer skill. The CLI's only dep is
# pillow (auto-installed by `uv run` from the inline # /// script block);
# this just makes sure `uv` exists and warms the cache. Safe to re-run;
# never blocks.

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
say "warming pillow into the uv cache"
if uv run "$SCRIPT_DIR/figure_compose.py" --help >/dev/null; then
    say "deps warmed — the first uv run figure_compose.py call will be fast / offline"
else
    warn "warm failed (offline?) — uv run will retry on first use; not fatal."
fi

say "figure-composer ready. Try:"
say "  uv run $SCRIPT_DIR/figure_compose.py --help"
