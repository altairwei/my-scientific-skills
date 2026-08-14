# bioinformatics/locus-novelty/scripts/apis/pubmed.py
"""NCBI E-utilities efetch — PubMed abstracts for supporting-study evidence."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Optional

import _common

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _client(transport=None) -> _common.HttpClient:
    return _common.HttpClient(BASE, rate=3.0, transport=transport, cache_dir=_common.cache_dir())


def abstracts(pmids: list[str], client: Optional[_common.HttpClient] = None) -> dict[str, str]:
    """Return {pmid: abstract_text} for the given PMIDs (empty string if absent).

    Batches up to 200 PMIDs per efetch call. efetch returns XML, so use the raw
    httpx client (like ldlink) — HttpClient.get parses JSON.
    """
    out: dict[str, str] = {}
    if not pmids:
        return out
    c = client or _client()
    for i in range(0, len(pmids), 200):
        batch = pmids[i:i + 200]
        c._limiter.acquire()
        r = c._client.get("efetch.fcgi",
                          params={"db": "pubmed", "id": ",".join(batch), "retmode": "xml"})
        r.raise_for_status()
        out.update(_parse(r.text))
    return out


def _parse(xml_text: str) -> dict[str, str]:
    """Parse efetch XML -> {pmid: ' '.join(abstract chunks)}."""
    if not xml_text:
        return {}
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return {}
    out = {}
    for art in root.findall(".//PubmedArticle"):
        pmid_el = art.find(".//PMID")
        pmid = pmid_el.text if pmid_el is not None and pmid_el.text else ""
        if not pmid:
            continue
        chunks = [e.text for e in art.findall(".//Abstract/AbstractText") if e.text]
        out[pmid] = " ".join(chunks)
    return out
