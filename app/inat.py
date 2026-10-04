"""Minimal client for the public iNaturalist API (species autocomplete).

This is the seed of Fauna's species-identification backbone: iNaturalist's
taxonomy database covers essentially all wildlife, and the same API family
powers photo-based ID suggestions and range/occurrence data in later phases.
"""
from __future__ import annotations

import os

import httpx

INAT_BASE = "https://api.inaturalist.org/v1"


class INatAuthError(Exception):
    """Raised when photo ID can't reach iNaturalist's computer vision.

    `reason` is "no_token" (nothing configured) or "rejected" (the token
    was refused — iNaturalist JWTs expire after 24 hours, so this usually
    just means a fresh token is needed).
    """

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def get_api_token() -> str | None:
    """API token for the authenticated iNaturalist endpoints.

    Set INAT_API_TOKEN in the environment. (Tokens come from
    https://www.inaturalist.org/users/api_token via an OAuth app and
    expire after 24 hours.)
    """
    return os.getenv("INAT_API_TOKEN")


def _guess_mime(filename: str) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
        "gif": "image/gif",
    }.get(ext, "image/jpeg")


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


def identify_image(
    image_bytes: bytes,
    filename: str = "photo.jpg",
    lat: float | None = None,
    lng: float | None = None,
) -> list[dict]:
    """Score a photo with iNaturalist's computer vision.

    POSTs the image to /v1/computervision/score_image (multipart `image`
    field, optional lat/lng to geo-bias the scores). Returns ranked
    suggestions: taxon_id, common_name, scientific_name, rank, vision_score,
    combined_score, photo_url — best guess first.

    Raises INatAuthError when no token is configured or iNaturalist rejects
    it; raises httpx.HTTPError on transport/API failures.
    """
    token = get_api_token()
    if not token:
        raise INatAuthError("no_token")
    data: dict[str, str] = {}
    if lat is not None and lng is not None:
        data = {"lat": str(lat), "lng": str(lng)}
    resp = httpx.post(
        f"{INAT_BASE}/computervision/score_image",
        files={"image": (filename, image_bytes, _guess_mime(filename))},
        data=data,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )
    if resp.status_code == 401:
        raise INatAuthError("rejected")
    resp.raise_for_status()
    suggestions: list[dict] = []
    for item in resp.json().get("results", []):
        taxon = item.get("taxon") or {}
        photo = taxon.get("default_photo") or {}
        suggestions.append(
            {
                "taxon_id": taxon.get("id"),
                "common_name": taxon.get("preferred_common_name"),
                "scientific_name": taxon.get("name"),
                "rank": taxon.get("rank"),
                "vision_score": item.get("vision_score"),
                "combined_score": item.get("combined_score"),
                "photo_url": photo.get("medium_url") or photo.get("square_url"),
            }
        )
    return suggestions
