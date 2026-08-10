#!/usr/bin/env bash
# biomedical-data/bio-data/scripts/setup.sh
# One-shot readiness check for the bio-data MCP server. Idempotent — safe to
# re-run. The server self-bootstraps deps via `uv run` + # /// script, so this
# mostly ensures uv is present and warms the dep cache (good for offline /
# bad-network sessions). Optionally points the user at NCBI key/email config.
set -euo pipefail

say()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }

say "Checking uv..."
if ! command -v uv >/dev/null 2>&1; then
  say "uv not found — installing via official installer"
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # shellcheck disable=SC1091
  source "$HOME/.cargo/env" 2>/dev/null || true
fi
command -v uv >/dev/null 2>&1 || { echo "uv install failed — install manually: https://docs.astral.sh/uv"; exit 1; }

say "Warming dependencies (mcp, httpx, pydantic)..."
uv run --with mcp --with httpx --with pydantic python -c "import mcp, httpx, pydantic; print('deps ok')" >/dev/null

say "Optional: NCBI API key + contact email"
say "  Without an NCBI_API_KEY, E-utilities run at 3 req/s (10 req/s with one)."
say "  Set in ~/.claude/settings.json under the biomedical-data plugin's env:"
say '    {"env": {"NCBI_API_KEY": "<key>", "NCBI_CONTACT_EMAIL": "you@example.com"}}'
say "  (Skip if you don't have one — tools still work, just slower.)"

say "Done. Server will self-bootstrap on first launch via: uv run .../server.py"
