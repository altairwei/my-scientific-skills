# biomedical-data/bio-data/scripts/apis/opentargets.py
"""Open Targets Platform tools (GraphQL over POST)."""
from __future__ import annotations

import json
from typing import Optional

import _common

BASE = "https://api.platform.opentargets.org/api"

_SEARCH_Q = """
query($q: String!) {
  search(query: $q, entity: "target") { hits { id name } total }
}
"""
_ASSOC_Q = """
query($ensemblId: String!) {
  associations(ensemblId: $ensemblId) {
    rows { score disease { id name } }
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
    return {"hits": search.get("hits", []), "total": search.get("total", 0)}


def target_associations(ensembl_id: str, client: Optional[_common.HttpClient] = None):
    c = client or _client()
    data = _gql(c, _ASSOC_Q, {"ensemblId": ensembl_id})
    assoc = data.get("data", {}).get("associations", {})
    return {"rows": assoc.get("rows", [])}
