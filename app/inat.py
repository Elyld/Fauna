"""Minimal client for the public iNaturalist API (species autocomplete).

This is the seed of Fauna's species-identification backbone: iNaturalist's
taxonomy database covers essentially all wildlife, and the same API family
powers photo-based ID suggestions and range/occurrence data in later phases.
"""
from __future__ import annotations

import os

import httpx

INAT_BASE = "https://api.inaturalist.org/v1"


def _sanitize_no_proxy() -> None:
    """Drop malformed NO_PROXY entries (bracketed IPv6 literals like "[::1]")
    that crash httpx's proxy-env parsing. Entries without brackets are left
    untouched, so this is a no-op on well-formed systems."""
    for var in ("NO_PROXY", "no_proxy"):
        val = os.environ.get(var)
        if val and "[" in val:
            os.environ[var] = ",".join(p for p in val.split(",") if "[" not in p)


_sanitize_no_proxy()


def search_taxa(query: str, per_page: int = 10) -> list[dict]:
    """Return top taxon matches for a free-text query.

    Each match: id, common_name, scientific_name, rank, iconic_taxon,
    photo_url, wikipedia_url.
    """
    query = (query or "").strip()
    if not query:
        return []
    resp = httpx.get(
        f"{INAT_BASE}/taxa/autocomplete",
        params={"q": query, "per_page": max(1, min(per_page, 30))},
        timeout=15.0,
    )
    resp.raise_for_status()
    results: list[dict] = []
    for taxon in resp.json().get("results", []):
        photo = taxon.get("default_photo") or {}
        results.append(
            {
                "id": taxon.get("id"),
                "common_name": taxon.get("preferred_common_name"),
                "scientific_name": taxon.get("name"),
                "rank": taxon.get("rank"),
                "iconic_taxon": taxon.get("iconic_taxon_name") or "",
                "photo_url": photo.get("medium_url") or photo.get("square_url"),
                "wikipedia_url": taxon.get("wikipedia_url"),
            }
        )
    return results
