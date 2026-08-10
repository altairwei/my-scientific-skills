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
from apis import pubmed  # noqa: E402  (imported incrementally as modules land)

from mcp.server import MCPServer  # noqa: E402

mcp = MCPServer("bio-data")


@mcp.tool()
def search_pubmed(query: str, retmax: int = 20) -> dict:
    """Search PubMed by query term; return matching PMIDs and the total count."""
    return pubmed.search_pubmed(query, retmax)


@mcp.tool()
def fetch_pubmed(pmids: list[str]) -> dict:
    """Fetch summary metadata (title, authors, journal) for a list of PMIDs."""
    return {"articles": pubmed.fetch_pubmed(pmids)}


@mcp.tool()
def find_related_articles(pmid: str) -> dict:
    """Find PubMed articles related to a given PMID (NCBI ELink)."""
    return pubmed.find_related_articles(pmid)


@mcp.tool()
def fetch_pmc_fulltext(pmc_ids: list[str]) -> dict:
    """Fetch full-text XML for PMC IDs (Europe PMC). Missing full text → null."""
    return pubmed.fetch_pmc_fulltext(pmc_ids)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
