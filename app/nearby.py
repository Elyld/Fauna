"""'Around you right now': species frequently observed near a home location.

Fauna asks iNaturalist "what's being seen near (lat, lng) lately?" and groups
the answer by taxon with counts. One cache entry per rounded location + month
(7-day TTL) — what's nearby changes seasonally, not daily.

Every public function is defensive: failures return graceful empty results,
never raise — a broken "nearby" must never break the page around it.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.inat import INAT_BASE
from app.models import NearbyCache

CACHE_TTL = timedelta(days=7)
RADIUS_KM = 25
TOP_N = 12
PER_PAGE = 200


def _cache_key(lat: float, lng: float, when: datetime | None = None) -> str:
    when = when or datetime.utcnow()
    return f"nearby:{lat:.2f}:{lng:.2f}:{when.strftime('%Y-%m')}"


def _read_entry(session: Session, key: str) -> dict | None:
    row = session.get(NearbyCache, key)
    if row is None:
        return None
    try:
        value = json.loads(row.payload_json or "null")
    except (ValueError, TypeError):
        value = None
    fresh = bool(row.fetched_at) and datetime.utcnow() - row.fetched_at < CACHE_TTL
    return {"value": value, "fresh": fresh}


def _write_entry(session: Session, key: str, value) -> None:
    payload = json.dumps(value)
    row = session.get(NearbyCache, key)
    if row is None:
        session.add(
            NearbyCache(cache_key=key, fetched_at=datetime.utcnow(), payload_json=payload)
        )
    else:
        row.fetched_at = datetime.utcnow()
        row.payload_json = payload
    session.commit()


def fetch_nearby_observations(lat: float, lng: float) -> list[dict]:
    """Recent research-grade iNaturalist observations near a point.

    Raises httpx.HTTPError on transport/API failures.
    """
    resp = httpx.get(
        f"{INAT_BASE}/observations",
        params={
            "lat": lat,
            "lng": lng,
            "radius": RADIUS_KM,
            "quality_grade": "research",
            "per_page": PER_PAGE,
            "order": "desc",
            "order_by": "observed_on",
        },
        timeout=20.0,
    )
    resp.raise_for_status()
    return resp.json().get("results", [])


def group_by_taxon(observations: list[dict], top_n: int = TOP_N) -> list[dict]:
    """Collapse raw observations into ranked taxon cards with counts.

    Each card: taxon_id, common_name, scientific_name, rank, photo_url,
    recent_count. Sorted by count desc, ties broken alphabetically so the
    order is deterministic.
    """
    groups: dict[int, dict] = {}
    counts: dict[int, int] = defaultdict(int)
    for obs in observations:
        taxon = obs.get("taxon") or {}
        taxon_id = taxon.get("id")
        if not taxon_id:
            continue
        counts[taxon_id] += 1
        if taxon_id not in groups:
            photo = taxon.get("default_photo") or {}
            groups[taxon_id] = {
                "taxon_id": taxon_id,
                "common_name": taxon.get("preferred_common_name"),
                "scientific_name": taxon.get("name"),
                "rank": taxon.get("rank"),
                "photo_url": photo.get("medium_url") or photo.get("square_url"),
            }
    ranked = sorted(
        groups.values(),
        key=lambda g: (-counts[g["taxon_id"]], (g["common_name"] or g["scientific_name"] or "").lower()),
    )
    for g in ranked:
        g["recent_count"] = counts[g["taxon_id"]]
    return ranked[:top_n]


def get_nearby(session: Session, lat: float, lng: float) -> dict:
    """Nearby species data: {taxa, from_cache, error}.

    Never raises — on failure returns stale cached data when available,
    otherwise an empty result with an error note.
    """
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return {"taxa": [], "from_cache": False, "error": "bad_location"}
    key = _cache_key(lat, lng)
    entry = _read_entry(session, key)
    if entry is not None and entry["fresh"]:
        return {"taxa": entry["value"] or [], "from_cache": True, "error": None}
    try:
        observations = fetch_nearby_observations(lat, lng)
    except Exception:
        if entry is not None:
            return {"taxa": entry["value"] or [], "from_cache": True, "error": "fetch_failed"}
        return {"taxa": [], "from_cache": False, "error": "fetch_failed"}
    taxa = group_by_taxon(observations)
    _write_entry(session, key, taxa)
    return {"taxa": taxa, "from_cache": False, "error": None}
