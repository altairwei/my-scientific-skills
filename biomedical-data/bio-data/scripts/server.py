#!/usr/bin/env python3
# biomedical-data/bio-data/scripts/server.py
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp", "httpx", "pydantic"]
# ///
"""bio-data MCP stdio server.

14 tools across 7 public biomedical APIs (NCBI E-utilities, ClinVar, dbSNP,
GWAS Catalog, Open Targets, gnomAD, MyGene, Ensembl). Clean-room against
public API docs — no bio-tools code. Mirrors data-science/interactive-repl's
MCPServer pattern.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import _common  # noqa: E402
# api modules are imported incrementally as their tools are wired (Tasks 6-13):
#   from apis import pubmed, mygene, clinvar, dbsnp, gwas_catalog, opentargets, gnomad, ensembl

from mcp.server import MCPServer  # noqa: E402

mcp = MCPServer("bio-data")

# Tools are registered in later tasks via @mcp.tool() wrappers defined below.


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
