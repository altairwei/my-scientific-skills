# biomedical-data/bio-data/scripts/apis/gnomad.py
"""gnomAD variant allele frequency (public browser API)."""
from __future__ import annotations

from typing import Optional

import _common

BASE = "https://gnomad.broadinstitute.org"


def _client(transport=None) -> _common.HttpClient:
    return _common.HttpClient(BASE, rate=2.0, transport=transport,
                              cache_dir=_common.cache_dir())


def gnomad_variant_frequency(variant: str, client: Optional[_common.HttpClient] = None):
    c = client or _client()
    # variant form: chrom-pos-ref-alt (GRCh38), e.g. 1-55051526-G-A
    data = c.get(f"api/variant/{variant}")
    return {
        "variant": variant,
        "genome": data.get("genome") or {},
        "exome": data.get("exome") or {},
    }
