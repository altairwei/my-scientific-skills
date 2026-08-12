# bioinformatics/locus-novelty/scripts/apis/ols.py
"""EBI Ontology Lookup Service (EFO) — trait -> IRI + ancestor distance."""
from __future__ import annotations

from typing import Optional
from urllib.parse import quote

import _common

BASE = "https://www.ebi.ac.uk/ols4/api"


def _client(transport=None) -> _common.HttpClient:
    return _common.HttpClient(BASE, rate=5.0, transport=transport, cache_dir=_common.cache_dir())


def efo_lookup(trait: str, client: Optional[_common.HttpClient] = None) -> Optional[str]:
    c = client or _client()
    data = c.get("search", {"q": trait, "ontology": "efo", "exact": "false", "rows": 1})
    docs = data.get("response", {}).get("docs", [])
    return docs[0]["iri"] if docs else None


def ancestors(iri: str, client: Optional[_common.HttpClient] = None) -> list[str]:
    """Return the list of ancestor EFO IRIs for a term (excluding self)."""
    c = client or _client()
    data = c.get(f"ontologies/efo/terms/{quote(iri, safe='')}/ancestors")
    return [t.get("iri") for t in (data.get("_embedded", {}).get("terms", [])) if t.get("iri") != iri]


def efo_distance(study_iri: Optional[str], prior_iri: Optional[str],
                 client: Optional[_common.HttpClient] = None) -> Optional[str]:
    """exact / parent / child / none. None if either term unresolved."""
    if not study_iri or not prior_iri:
        return None
    if study_iri == prior_iri:
        return "exact"
    study_anc = ancestors(study_iri, client=client)
    if prior_iri in study_anc:
        return "parent"            # prior is an ancestor of study -> study is a child of prior
    prior_anc = ancestors(prior_iri, client=client)
    if study_iri in prior_anc:
        return "child"             # study is an ancestor of prior -> prior is a child of study
    return "none"
