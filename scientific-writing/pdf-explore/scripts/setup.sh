#!/usr/bin/env bash
# scientific-writing/pdf-explore/scripts/setup.sh
# Idempotent pre-warm for the pdf-explore skill. `uv run scripts/pdf_explore.py …`
# auto-installs pypdfium2/pillow/pypdf from the inline # /// script metadata on
# first call anyway — this script just (1) makes sure `uv` exists and (2) warms
# uv's wheel cache so the first real call works offline / fast. Safe to re-run.
# Mirrors biomedical-data/bio-data/scripts/setup.sh.

set -euo pipefail

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }

# ── 1/3: uv ──────────────────────────────────────────────────────────────────
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

# ── 2/3: pre-warm the wheel cache ───────────────────────────────────────────
# `uv run --with <deps> python -c "import …"` resolves + caches the wheels
# without doing any real work, so the first `pdf_explore.py` call doesn't stall
# on a network fetch. After this, the deps work offline too.
say "warming the pypdfium2/pillow/pypdf wheel cache (may fetch on first run)…"
if uv run --with pypdfium2 --with pillow --with pypdf \
        python -c "import pypdfium2, PIL, pypdf; print('deps ok')" >/dev/null 2>&1; then
    say "deps warmed — the first uv run pdf_explore.py call will be fast / offline"
else
    warn "dep warm failed (offline? blocked registry?). The inline # /// script deps will retry on first `uv run pdf_explore.py …` — re-run this script when you're online for a clean pre-warm."
    # don't fail: uv run auto-installs on first call, so setup.sh is advisory.
fi

# ── 3/3: status ─────────────────────────────────────────────────────────────
say "pdf-explore ready. Try:"
say "  uv run $(dirname "$(realpath "$0")")/pdf_explore.py --help"
