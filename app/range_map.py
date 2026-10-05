"""Range maps: research-grade iNaturalist observation points per taxon.

Fauna asks iNaturalist "where is this animal normally seen?" and plots the
answer. Two cache layers, both 7-day TTL, so page views don't hammer the API:
  name:<scientific name>  -> {"taxon_id": 4242}   (name resolution)
  taxon:<id>              -> [[lat, lng], ...]    (observation points)
Every public function is defensive: failures return graceful empty results,
never raise — a broken map must never break the page around it.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from app.inat import INAT_BASE, search_taxa
from app.models import RangeCache

CACHE_TTL = timedelta(days=7)
MAX_POINTS = 500


def _name_key(name: str) -> str:
    return f"name:{(name or '').strip().lower()}"


def _taxon_key(taxon_id: int) -> str:
    return f"taxon:{taxon_id}"


def _read_entry(session: Session, key: str) -> dict | None:
    """Cached entry: {value, fetched_at, fresh} or None."""
    row = session.get(RangeCache, key)
    if row is None:
        return None
    try:
        value = json.loads(row.points_json or "null")
    except (ValueError, TypeError):
        value = None
    fetched_at = row.fetched_at
    fresh = bool(fetched_at) and datetime.utcnow() - fetched_at < CACHE_TTL
    return {"value": value, "fetched_at": fetched_at, "fresh": fresh}


def _write_entry(session: Session, key: str, value) -> None:
    payload = json.dumps(value)
    row = session.get(RangeCache, key)
    if row is None:
        session.add(
            RangeCache(taxon_key=key, fetched_at=datetime.utcnow(), points_json=payload)
        )
    else:
        row.fetched_at = datetime.utcnow()
        row.points_json = payload
    session.commit()


def resolve_taxon_id(scientific_name: str) -> int | None:
    """Best-effort iNaturalist taxon id for a scientific name.

    Prefers an exact name match, otherwise takes the top autocomplete hit.
    Returns None when nothing matches. Raises httpx.HTTPError on transport
    failures (callers decide how to handle it).
    """
    name = (scientific_name or "").strip()
    if not name:
        return None
    matches = search_taxa(name, per_page=5)
    if not matches:
        return None
    lowered = name.lower()
    for m in matches:
        if (m.get("scientific_name") or "").lower() == lowered and m.get("id"):
            return m["id"]
    return matches[0].get("id")


def fetch_range_points(taxon_id: int) -> list[list[float]]:
    """Research-grade observation coordinates for a taxon: [[lat, lng], ...].

    Raises httpx.HTTPError on transport/API failures.
    """
    resp = httpx.get(
        f"{INAT_BASE}/observations",
        params={
            "taxon_id": taxon_id,
            "quality_grade": "research",
            "per_page": 200,
            "order_by": "observed_on",
        },
        timeout=20.0,
    )
    resp.raise_for_status()
    points: list[list[float]] = []
    for obs in resp.json().get("results", []):
        geo = obs.get("geojson") or {}
        coords = geo.get("coordinates") or []
        if len(coords) >= 2 and isinstance(coords[0], (int, float)):
            points.append([coords[1], coords[0]])  # geojson is [lng, lat]
        if len(points) >= MAX_POINTS:
            break
    return points


def get_range(session: Session, scientific_name: str) -> dict:
    """Range data for a species: {taxon_id, points, from_cache, error}.

    Never raises — on any failure returns cached-stale data when available,
    otherwise an empty result with an error note.
    """
    name = (scientific_name or "").strip()
    if not name:
        return {"taxon_id": None, "points": [], "from_cache": False, "error": "no_name"}

    # Layer 1: name -> taxon id (misses cached as null, so unknown names
    # don't re-query the taxonomy on every view).
    name_entry = _read_entry(session, _name_key(name))
    stale_name_value = name_entry["value"] if name_entry else None
    if name_entry is not None and name_entry["fresh"]:
        taxon_id = name_entry["value"]
        name_cached = True
    else:
        try:
            taxon_id = resolve_taxon_id(name)
        except Exception:
            if name_entry is not None:
                taxon_id = stale_name_value
                name_cached = True
            else:
                return {
                    "taxon_id": None,
                    "points": [],
                    "from_cache": False,
                    "error": "lookup_failed",
                }
        else:
            _write_entry(session, _name_key(name), taxon_id)
            name_cached = False
    if taxon_id is None:
        return {
            "taxon_id": None,
            "points": [],
            "from_cache": name_cached,
            "error": "no_taxon_match",
        }

    # Layer 2: taxon id -> points.
    taxon_entry = _read_entry(session, _taxon_key(taxon_id))
    if taxon_entry is not None and taxon_entry["fresh"]:
        return {
            "taxon_id": taxon_id,
            "points": taxon_entry["value"] or [],
            "from_cache": True,
            "error": None,
        }
    try:
        points = fetch_range_points(taxon_id)
    except Exception:
        if taxon_entry is not None:
            return {
                "taxon_id": taxon_id,
                "points": taxon_entry["value"] or [],
                "from_cache": True,
                "error": "fetch_failed",
            }
        return {
            "taxon_id": taxon_id,
            "points": [],
            "from_cache": False,
            "error": "fetch_failed",
        }
    _write_entry(session, _taxon_key(taxon_id), points)
    return {
        "taxon_id": taxon_id,
        "points": points,
        "from_cache": False,
        "error": "no_observations" if not points else None,
    }
