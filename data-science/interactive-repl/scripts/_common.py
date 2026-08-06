"""Shared helpers for the interactive-repl MCP servers (pure, no I/O).

Output capping, plot-dir management, JSON-line framing. No I/O of its own
beyond plot_dir() creating the directory — fully unit-testable.
"""
import json, os


def cap_output(text: str, max_bytes: int = 1024 * 1024) -> tuple[str, bool]:
    """Cap text to ~max_bytes UTF-8; append a marker if truncated.

    Returns (capped_text, truncated). The marker makes truncation visible to
    the agent so it never mistakes a capped blob for complete output.
    """
    b = text.encode("utf-8", "surrogatepass")
    if len(b) <= max_bytes:
        return text, False
    head = b[:max_bytes].decode("utf-8", "ignore")
    dropped = len(b) - max_bytes
    return f"{head}\n... (truncated, {dropped} further bytes dropped)", True


def never_empty(stdout: str, stderr: str) -> str:
    """Surface stderr if stdout is empty; never return an empty string.

    The agent must always see *something* after a run (r-cell's _show_output grace:
    if START scrolled off, show the tail up to END instead of going empty).
    """
    if stdout.strip():
        return stdout
    if stderr.strip():
        return f"[stderr only]\n{stderr}"
    return "[no output]"


def plot_dir() -> str:
    """Persistent plot directory under ${CLAUDE_PLUGIN_DATA}/plots (temp fallback)."""
    base = os.environ.get("CLAUDE_PLUGIN_DATA") or "/tmp/interactive-repl-data"
    d = os.path.join(base, "plots")
    os.makedirs(d, exist_ok=True)
    return d


def encode_line(obj: dict) -> str:
    """Serialize obj as a single JSON line (newlines in values are escaped)."""
    return json.dumps(obj, ensure_ascii=False) + "\n"


def decode_line(line: str) -> dict:
    """Parse one JSON line (trailing newline tolerated)."""
    return json.loads(line)
