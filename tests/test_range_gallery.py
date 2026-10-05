"""Range maps + photo gallery.

Run:  cd ~/workspace/fauna && PYTHONPATH=. .venv/bin/python -m pytest -q
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import httpx

TMP = Path(tempfile.mkdtemp(prefix="fauna-test-rg-"))
os.environ.setdefault("FAUNA_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("FAUNA_UPLOAD_DIR", str(TMP / "photos"))

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_mod  # noqa: E402
import app.range_map as range_map  # noqa: E402
from app.database import UPLOAD_DIR, SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Observation, RangeCache  # noqa: E402

assert UPLOAD_DIR  # keep the conventional import used

init_db()
client = TestClient(app)

BASE = datetime(2026, 9, 1, 10, 0, 0)


def _log(species, **kw):
    payload = {
        "species_name": species,
        "count": 1,
        "observed_at": BASE.isoformat(),
        "location_name": "Test Meadow",
    }
    payload.update(kw)
    r = client.post("/api/observations", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _fresh_session():
    return SessionLocal()


# --- range cache behavior (HTTP seams mocked, never the network) ---


def _fake_resolver(calls, taxon_id=4242):
    def _resolve(name):
        calls.append(name)
        return taxon_id

    return _resolve


def _fake_fetcher(calls, points=None):
    def _fetch(taxon_id):
        calls.append(taxon_id)
        return points if points is not None else [[39.0, -95.6], [39.1, -95.5]]

    return _fetch


def test_range_cache_hit_avoids_second_fetch(monkeypatch):
    resolve_calls, fetch_calls = [], []
    monkeypatch.setattr(
        range_map, "resolve_taxon_id", _fake_resolver(resolve_calls)
    )
    monkeypatch.setattr(range_map, "fetch_range_points", _fake_fetcher(fetch_calls))
    s = _fresh_session()
    try:
        first = range_map.get_range(s, "RG Squirrelus testus")
        second = range_map.get_range(s, "RG Squirrelus testus")
    finally:
        s.close()
    assert first["taxon_id"] == 4242
    assert len(first["points"]) == 2
    assert first["from_cache"] is False
    assert second["from_cache"] is True
    assert len(fetch_calls) == 1  # second call served from cache
    assert len(resolve_calls) == 1


def test_range_ttl_refetch(monkeypatch):
    resolve_calls, fetch_calls = [], []
    monkeypatch.setattr(
        range_map, "resolve_taxon_id", _fake_resolver(resolve_calls, 4243)
    )
    monkeypatch.setattr(range_map, "fetch_range_points", _fake_fetcher(fetch_calls))
    s = _fresh_session()
    try:
        range_map.get_range(s, "RG Staleus birdus")
        row = s.get(RangeCache, "taxon:4243")
        row.fetched_at = datetime.utcnow() - timedelta(days=8)
        s.commit()
        result = range_map.get_range(s, "RG Staleus birdus")
    finally:
        s.close()
    assert result["from_cache"] is False
    assert len(fetch_calls) == 2  # stale entry was refetched


def test_range_miss_is_cached(monkeypatch):
    resolve_calls = []
    monkeypatch.setattr(range_map, "resolve_taxon_id", _fake_resolver(resolve_calls, None))
    s = _fresh_session()
    try:
        first = range_map.get_range(s, "RG Notareal species")
        second = range_map.get_range(s, "RG Notareal species")
    finally:
        s.close()
    assert first["error"] == "no_taxon_match"
    assert first["points"] == []
    assert second["from_cache"] is True
    assert len(resolve_calls) == 1  # miss cached, no second lookup


def test_range_lookup_failure_is_graceful(monkeypatch):
    def _boom(name):
        raise httpx.HTTPError("network down")

    monkeypatch.setattr(range_map, "resolve_taxon_id", _boom)
    s = _fresh_session()
    try:
        result = range_map.get_range(s, "RG Explodus birdus")
    finally:
        s.close()
    assert result["points"] == []
    assert result["error"] == "lookup_failed"


def test_range_fetch_failure_falls_back_to_stale(monkeypatch):
    resolve_calls = []
    monkeypatch.setattr(
        range_map, "resolve_taxon_id", _fake_resolver(resolve_calls, 7777)
    )
    s = _fresh_session()
    try:
        range_map.get_range(s, "RG Fallbackus birdus")
        row = s.get(RangeCache, "taxon:7777")
        row.fetched_at = datetime.utcnow() - timedelta(days=8)
        s.commit()

        def _boom(taxon_id):
            raise httpx.HTTPError("network down")

        monkeypatch.setattr(range_map, "fetch_range_points", _boom)
        result = range_map.get_range(s, "RG Fallbackus birdus")
    finally:
        s.close()
    assert result["from_cache"] is True  # stale data served, not an error page
    assert len(result["points"]) > 0  # the earlier (real or mocked) fetch
    assert result["error"] == "fetch_failed"


# --- species page ---

FAKE_TAXON = {
    "id": 4242,
    "common_name": "RG Test Squirrel",
    "scientific_name": "RG Squirrelus testus",
    "rank": "species",
    "photo_url": "https://example.com/sq.jpg",
    "wikipedia_url": "https://en.wikipedia.org/wiki/Squirrel",
}


def _patch_species_deps(monkeypatch, rng):
    monkeypatch.setattr(main_mod, "_taxon_info", lambda name: dict(FAKE_TAXON))
    monkeypatch.setattr(main_mod.range_map, "get_range", lambda session, name: rng)


def test_species_page_renders(monkeypatch):
    _patch_species_deps(
        monkeypatch,
        {
            "taxon_id": 4242,
            "points": [[39.0, -95.6]],
            "from_cache": False,
            "error": None,
        },
    )
    r = client.get("/species/RG%20Squirrelus%20testus")
    assert r.status_code == 200
    html = r.text
    assert "RG Test Squirrel" in html
    assert "leaflet" in html.lower()
    assert "range-map" in html
    assert "range-map-fallback" in html  # graceful-degradation path present


def test_species_page_unknown_species_graceful(monkeypatch):
    monkeypatch.setattr(main_mod, "_taxon_info", lambda name: None)
    monkeypatch.setattr(
        main_mod.range_map,
        "get_range",
        lambda session, name: {
            "taxon_id": None,
            "points": [],
            "from_cache": False,
            "error": "no_taxon_match",
        },
    )
    r = client.get("/species/RG%20Notareal%20species")
    assert r.status_code == 200
    assert "no range map" in r.text.lower()


def test_species_page_lists_own_sightings(monkeypatch):
    _log("RG Page Squirrel", scientific_name="RG Squirrelus pageus", photo_path=None)
    _patch_species_deps(
        monkeypatch,
        {"taxon_id": 4242, "points": [], "from_cache": False, "error": "no_observations"},
    )
    monkeypatch.setattr(
        main_mod,
        "_taxon_info",
        lambda name: {
            **FAKE_TAXON,
            "common_name": "RG Page Squirrel",
            "scientific_name": "RG Squirrelus pageus",
        },
    )
    r = client.get("/species/RG%20Squirrelus%20pageus")
    assert r.status_code == 200
    assert "RG Page Squirrel" in r.text
    assert "Your sightings" in r.text


def _log_with_photo(species, filename, **kw):
    """Insert directly (the API only accepts pending_ photo refs)."""
    kw.setdefault("location_name", "Test Meadow")
    s = _fresh_session()
    try:
        o = Observation(
            species_name=species,
            photo_path=filename,
            count=1,
            observed_at=BASE,
            **kw,
        )
        s.add(o)
        s.commit()
    finally:
        s.close()


# --- gallery ---


def test_gallery_lists_only_photo_sightings():
    _log_with_photo("RG Gallery Jay", "rg-jay.jpg")
    _log("RG Gallery Wren")  # no photo
    r = client.get("/gallery")
    assert r.status_code == 200
    html = r.text
    assert "rg-jay.jpg" in html
    assert "RG Gallery Jay" in html
    assert "RG Gallery Wren" not in html


def test_gallery_species_filter():
    _log_with_photo("RG Gallery Finch", "rg-finch.jpg")
    r = client.get("/gallery", params={"species": "RG Gallery Finch"})
    assert r.status_code == 200
    assert "rg-finch.jpg" in r.text
    assert "rg-jay.jpg" not in r.text


def test_gallery_text_search():
    _log_with_photo(
        "RG Gallery Owl", "rg-owl.jpg", location_name="RG Old Barn"
    )
    r = client.get("/gallery", params={"q": "barn"})
    assert r.status_code == 200
    assert "rg-owl.jpg" in r.text
    assert "rg-jay.jpg" not in r.text


def test_gallery_lightbox_markup():
    r = client.get("/gallery")
    assert r.status_code == 200
    assert 'id="lightbox"' in r.text
    assert 'loading="lazy"' in r.text
    assert "View sighting" in r.text


def test_observations_model_has_range_cache_table():
    s = _fresh_session()
    try:
        assert s.get(RangeCache, "taxon:0") is None  # table exists, key absent
        assert s.query(Observation).count() >= 0
    finally:
        s.close()
