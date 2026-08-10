# biomedical-data/bio-data/scripts/apis/opentargets.py
"""Open Targets Platform tools (GraphQL over POST, API v4)."""
from __future__ import annotations

import json
from typing import Optional

import _common

BASE = "https://api.platform.opentargets.org/api/v4"

_SEARCH_Q = """
query($q: String!) {
  search(queryString: $q, entityNames: ["target"]) {
    hits { id object { ... on Target { id approvedSymbol } } }
    total
  }
}
"""
_ASSOC_Q = """
query($ensemblId: String!) {
  target(ensemblId: $ensemblId) {
    associatedDiseases { rows { score disease { id name } } }
  }
}
"""


def _client(transport=None) -> _common.HttpClient:
    return _common.HttpClient(BASE, rate=3.0, transport=transport,
                              cache_dir=_common.cache_dir())


def _gql(client: _common.HttpClient, query: str, variables: dict) -> dict:
    body = json.dumps({"query": query, "variables": variables})
    return client.post("graphql", content=body, headers={"Content-Type": "application/json"})


def search_targets(query: str, client: Optional[_common.HttpClient] = None):
    c = client or _client()
    data = _gql(c, _SEARCH_Q, {"q": query})
    search = data.get("data", {}).get("search", {})
    hits = [
        {"id": h.get("id"), "name": (h.get("object") or {}).get("approvedSymbol")}
        for h in search.get("hits", [])
    ]
    return {"hits": hits, "total": search.get("total", 0)}


def target_associations(ensembl_id: str, client: Optional[_common.HttpClient] = None):
    c = client or _client()
    data = _gql(c, _ASSOC_Q, {"ensemblId": ensembl_id})
    assoc = data.get("data", {}).get("target", {}).get("associatedDiseases", {})
    return {"rows": assoc.get("rows", [])}
