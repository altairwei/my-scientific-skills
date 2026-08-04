#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = []
# ///
# pipeline-maker asset — deterministic validation helper.
# Runs `snakemake -n --cores 1` in the workflow directory, classifies the
# high-frequency Snakemake exceptions, prints the full stderr for Claude to
# read, and falls back to a static-structure check if snakemake is absent.
# It does NOT attempt fixes. Called by Claude inside the validation loop.

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# Real high-frequency exceptions observed in the WGS session data.
CLASSIFY = [
    (re.compile(r"ProtectedOutputException"), "rerun-and-metadata.md",
     "a protected() output would be overwritten — likely the stale-code trap"),
    (re.compile(r"IncompleteFilesException"), "rerun-and-metadata.md",
     "files marked incomplete (force-stopped) — resume with --rerun-incomplete"),
    (re.compile(r"Code has changed"), "rerun-and-metadata.md",
     "a rule's shell text/params/conda env changed — cleanup-metadata the whole subtree"),
    (re.compile(r"MissingInputException"), "debugging.md",
     "no rule produces an input, or a wildcard resolves to nothing"),
    (re.compile(r"MissingOutputException"), "debugging.md",
     "a rule did not produce a declared output"),
    (re.compile(r"AmbiguousRuleException"), "debugging.md",
     "multiple rules can produce the same output — constrain wildcards or set ruleorder"),
    (re.compile(r"WildcardError"), "debugging.md",
     "unconstrained or ambiguous wildcard"),
    (re.compile(r"WorkflowError"), "debugging.md",
     "broad snakemake error — read the message"),
]

RULE_RE = re.compile(r"^\s*rule\s+(\w+)\s*:", re.MULTILINE)
OUTPUT_RE = re.compile(r"^\s*output:\s*(.*)$", re.MULTILINE)
SHELL_OR_RUN_RE = re.compile(r"^\s*(shell|run):\s*(.*)$", re.MULTILINE)


def run_dryrun(cwd: Path) -> tuple[int, str, str]:
    smk = shutil.which("snakemake")
    if smk is None:
        return -1, "", "snakemake not found on PATH"
    proc = subprocess.run(
        [smk, "-n", "--cores", "1"],
        cwd=cwd, capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def classify(stderr: str) -> list[str]:
    hits = []
    for pat, ref, hint in CLASSIFY:
        if pat.search(stderr):
            hits.append(f"  - {pat.pattern} -> see {ref}: {hint}")
    return hits


def static_check(cwd: Path) -> tuple[int, list[str]]:
    """Fallback when snakemake is absent. Best-effort structural checks."""
    issues = []
    snakefiles = list(cwd.glob("Snakefile")) + list(cwd.glob("workflow/Snakefile")) + list(cwd.glob("workflow/rules/*.smk"))
    if not snakefiles:
        return 1, ["no Snakefile or workflow/rules/*.smk found"]
    seen = set()
    for sf in snakefiles:
        text = sf.read_text()
        for m in RULE_RE.finditer(text):
            name = m.group(1)
            if name in seen:
                issues.append(f"duplicate rule name: {name}")
            seen.add(name)
        # Heuristic: each rule block should have output + (shell|run). This is
        # approximate (Snakemake DSL is not pure Python) — real validation is
        # the dry-run. Only flag the obviously broken.
        for block in re.split(r"(?=\n\s*rule\s+\w+\s*:)", text):
            if "rule " not in block:
                continue
            if not OUTPUT_RE.search(block):
                continue  # target rules (rule all) may have no output
            if not SHELL_OR_RUN_RE.search(block) and "script:" not in block:
                issues.append(f"rule block without shell/run/script:\n{block.strip()[:120]}")
    return (0 if not issues else 1), issues


def main(argv: list[str]) -> int:
    cwd = Path(argv[1] if len(argv) > 1 else ".")
    if not cwd.exists():
        print(f"validate-workflow: no such dir: {cwd}", file=sys.stderr)
        return 2

    code, stdout, stderr = run_dryrun(cwd)
    if code == -1:
        print("WARNING: snakemake not on PATH — falling back to static-structure check.")
        print("Real validation requires installing snakemake. Output is UNVALIDATED.\n")
        sc_code, issues = static_check(cwd)
        for i in issues:
            print(f"  {i}")
        print(f"\nstatic check: {'PASS (unvalidated)' if sc_code == 0 else 'FAIL'}")
        return sc_code

    print("=== snakemake -n --cores 1 ===")
    if stdout:
        print(stdout)
    if stderr:
        print("=== STDERR (verbatim) ===")
        print(stderr)
    hits = classify(stderr)
    if hits:
        print("\n=== classified (pointers) ===")
        for h in hits:
            print(h)
    print(f"\nexit: {code}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
