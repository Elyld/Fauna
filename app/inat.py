"""Minimal client for the public iNaturalist API (species autocomplete).

This is the seed of Fauna's species-identification backbone: iNaturalist's
taxonomy database covers essentially all wildlife, and the same API family
powers photo-based ID suggestions and range/occurrence data in later phases.
"""
from __future__ import annotations

import httpx

INAT_BASE = "https://api.inaturalist.org/v1"


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
