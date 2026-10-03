"""Live iNaturalist API check — hits the real api.inaturalist.org.

This is a live-network test. CI-style runs skip it; it only runs when
FAUNA_LIVE_TESTS=1 is set:

    FAUNA_LIVE_TESTS=1 PYTHONPATH=. .venv/bin/python -m pytest tests/test_inat_live.py -q
"""
from __future__ import annotations

import os

import pytest

# Sandbox-only workaround: this runtime's NO_PROXY contains bracketed IPv6
# literals (e.g. "[::1]") that crash httpx's proxy-env parsing. Strip them so
# the live check can run; real deployments don't have these entries.
for _var in ("NO_PROXY", "no_proxy"):
    _val = os.environ.get(_var)
    if _val:
        os.environ[_var] = ",".join(p for p in _val.split(",") if "[" not in p)

pytestmark = pytest.mark.skipif(
    os.environ.get("FAUNA_LIVE_TESTS") != "1",
    reason="live-network test; set FAUNA_LIVE_TESTS=1 to run",
)

from app import inat  # noqa: E402


def test_taxa_autocomplete_robin():
    results = inat.search_taxa("robin", per_page=5)
    assert results, "expected at least one taxon match"
    first = results[0]
    assert first["scientific_name"]
    assert first["rank"]
    assert any("robin" in (r["common_name"] or "").lower() for r in results)
