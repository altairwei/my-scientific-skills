# biomedical-data/bio-data/scripts/apis/gnomad.py
"""gnomAD variant allele frequency (public GraphQL API, dataset gnomad_r4 / GRCh38)."""
from __future__ import annotations

import json
from typing import Optional

import _common

BASE = "https://gnomad.broadinstitute.org"

_VARIANT_Q = """
query($id: String!) {
  variant(variantId: $id, dataset: gnomad_r4) {
    variant_id
    genome { ac an af }
    exome { ac an af }
  }
}
"""


def _client(transport=None) -> _common.HttpClient:
    return _common.HttpClient(BASE, rate=2.0, transport=transport,
                              cache_dir=_common.cache_dir())


def gnomad_variant_frequency(variant: str, client: Optional[_common.HttpClient] = None):
    c = client or _client()
    # variant form: chrom-pos-ref-alt (GRCh38), e.g. 7-117559593-ATCT-A
    body = json.dumps({"query": _VARIANT_Q, "variables": {"id": variant}})
    data = c.post("api", content=body, headers={"Content-Type": "application/json"})
    v = data.get("data", {}).get("variant") or {}
    return {
        "variant": variant,
        "genome": v.get("genome") or {},
        "exome": v.get("exome") or {},
    }
