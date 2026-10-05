"""Batch 2 tests: multi-photo sightings, sightings map, nearby, wishlist, offline.

Run:  cd ~/workspace/fauna && PYTHONPATH=. .venv/bin/python -m pytest -q
"""
from __future__ import annotations

import base64
import io
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fauna-test-batch2-"))
os.environ.setdefault("FAUNA_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("FAUNA_UPLOAD_DIR", str(TMP / "photos"))

from fastapi.testclient import TestClient  # noqa: E402

import app.main as main_mod  # noqa: E402
import app.nearby as nearby_mod  # noqa: E402
from app import database as db_mod  # noqa: E402
from app.database import UPLOAD_DIR, SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Observation, ObservationPhoto  # noqa: E402

assert UPLOAD_DIR  # keep the conventional import used

init_db()
client = TestClient(app)

# 1x1 red PNG — tiny but a real image file.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _log(payload: dict) -> dict:
    r = client.post("/api/observations", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def _upload_multi(obs_id: int, n: int = 2) -> dict:
    files = [
        ("files", (f"p{i}.png", io.BytesIO(PNG), "image/png")) for i in range(n)
    ]
    r = client.post(f"/api/observations/{obs_id}/photos", files=files)
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------------------
# 1. Multi-photo sightings
# ---------------------------------------------------------------------------


def test_multi_photo_add_list_and_cover():
    obs = _log({"species_name": "Multi Bird", "scientific_name": "Multus avius"})
    body = _upload_multi(obs["id"], 2)
    assert len(body["photos"]) == 2
    assert body["photo_path"] == body["photos"][0]["photo_path"]  # first is cover
    # files really landed on disk
    for p in body["photos"]:
        assert (UPLOAD_DIR / Path(p["photo_path"]).name).exists()


def test_multi_photo_delete_one_and_cover_fallback():
    obs = _log({"species_name": "Cover Bird", "scientific_name": "Coverus avius"})
    body = _upload_multi(obs["id"], 2)
    cover_id = body["photos"][0]["id"]
    other_path = body["photos"][1]["photo_path"]

    r = client.delete(f"/api/observations/{obs['id']}/photos/{cover_id}")
    assert r.status_code == 200, r.text
    after = r.json()
    assert len(after["photos"]) == 1
    # cover falls back to the remaining photo
    assert after["photo_path"] == other_path
    # deleted file is gone from disk
    assert not (UPLOAD_DIR / Path(body["photos"][0]["photo_path"]).name).exists()


def test_single_photo_endpoint_still_sets_cover():
    obs = _log({"species_name": "Single Bird", "scientific_name": "Singulus avius"})
    r = client.post(
        f"/api/observations/{obs['id']}/photo",
        files={"file": ("s.png", io.BytesIO(PNG), "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["photo_path"]
    assert len(body["photos"]) == 1  # tracked in the multi-photo table too
    # a second single upload replaces the cover (classic behavior)
    old_path = body["photo_path"]
    r = client.post(
        f"/api/observations/{obs['id']}/photo",
        files={"file": ("s2.png", io.BytesIO(PNG), "image/png")},
    )
    body = r.json()
    assert body["photo_path"] != old_path
    assert len(body["photos"]) == 1
    assert not (UPLOAD_DIR / Path(old_path).name).exists()


def test_delete_observation_removes_all_photo_files():
    obs = _log({"species_name": "Doomed Bird", "scientific_name": "Doomus avius"})
    body = _upload_multi(obs["id"], 3)
    paths = [p["photo_path"] for p in body["photos"]]
    r = client.delete(f"/api/observations/{obs['id']}")
    assert r.status_code == 200
    for name in paths:
        assert not (UPLOAD_DIR / Path(name).name).exists()
    with SessionLocal() as s:
        assert s.query(ObservationPhoto).filter_by(observation_id=obs["id"]).count() == 0


def test_backfill_gives_legacy_photos_a_row():
    # Simulate a pre-multi-photo sighting: photo_path set, no photo rows.
    with SessionLocal() as s:
        legacy = Observation(species_name="Legacy Bird", photo_path="legacy123.png")
        s.add(legacy)
        s.commit()
        legacy_id = legacy.id
    (UPLOAD_DIR / "legacy123.png").write_bytes(PNG)
    db_mod._backfill_photo_rows()
    with SessionLocal() as s:
        rows = s.query(ObservationPhoto).filter_by(observation_id=legacy_id).all()
        assert len(rows) == 1
        assert rows[0].photo_path == "legacy123.png"
    r = client.get(f"/api/observations/{legacy_id}")
    assert len(r.json()["photos"]) == 1
    # idempotent: run it again, still one row
    db_mod._backfill_photo_rows()
    with SessionLocal() as s:
        assert s.query(ObservationPhoto).filter_by(observation_id=legacy_id).count() == 1


def test_photo_upload_rejects_bad_extension():
    obs = _log({"species_name": "Evil Bird", "scientific_name": "Evilus avius"})
    r = client.post(
        f"/api/observations/{obs['id']}/photos",
        files={"files": ("x.exe", io.BytesIO(b"nope"), "application/octet-stream")},
    )
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# 2. Sightings map
# ---------------------------------------------------------------------------


def test_map_page_pins_sightings_with_location():
    _log(
        {
            "species_name": "Map Robin",
            "scientific_name": "Turdus migratorius",
            "latitude": 39.05,
            "longitude": -95.68,
            "location_name": "Topeka backyard",
        }
    )
    r = client.get("/map")
    assert r.status_code == 200
    assert "39.05" in r.text  # pin data embedded
    assert "leaflet" in r.text.lower()
    assert "Nothing to pin yet" not in r.text


def test_map_page_species_filter_and_empty_state():
    r = client.get("/map", params={"species": "Map Robin"})
    assert r.status_code == 200
    assert "39.05" in r.text
    r = client.get("/map", params={"species": "No Such Bird Anywhere"})
    assert r.status_code == 200
    assert "Nothing to pin yet" in r.text


# ---------------------------------------------------------------------------
# 3. Nearby
# ---------------------------------------------------------------------------

CANNED_NEARBY = [
    {
        "id": 101,
        "taxon": {
            "id": 10,
            "name": "Turdus migratorius",
            "preferred_common_name": "American Robin",
            "rank": "species",
            "default_photo": {"medium_url": "https://example.com/robin.jpg"},
        },
    },
    {
        "id": 102,
        "taxon": {
            "id": 10,
            "name": "Turdus migratorius",
            "preferred_common_name": "American Robin",
            "rank": "species",
            "default_photo": {"medium_url": "https://example.com/robin.jpg"},
        },
    },
    {
        "id": 103,
        "taxon": {
            "id": 20,
            "name": "Cardinalis cardinalis",
            "preferred_common_name": "Northern Cardinal",
            "rank": "species",
            "default_photo": {"medium_url": "https://example.com/cardinal.jpg"},
        },
    },
    {"id": 104, "taxon": None},  # unidentified — skipped
]


def _set_home(lat="39.05", lng="-95.68", name="Home"):
    r = client.put(
        "/api/settings",
        json={"home_latitude": lat, "home_longitude": lng, "home_name": name},
    )
    assert r.status_code == 200, r.text


def test_nearby_grouping_and_cache(monkeypatch):
    calls = []

    def fake_fetch(lat, lng):
        calls.append((lat, lng))
        return CANNED_NEARBY

    monkeypatch.setattr(nearby_mod, "fetch_nearby_observations", fake_fetch)
    _set_home()
    r = client.get("/api/nearby")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["error"] is None
    assert data["from_cache"] is False
    taxa = data["taxa"]
    assert [t["scientific_name"] for t in taxa] == [
        "Turdus migratorius",
        "Cardinalis cardinalis",
    ]
    assert taxa[0]["recent_count"] == 2
    assert taxa[0]["photo_url"] == "https://example.com/robin.jpg"

    # second call comes from cache — no refetch
    r = client.get("/api/nearby")
    assert r.json()["from_cache"] is True
    assert len(calls) == 1

    # expire the cache entry -> refetch
    with SessionLocal() as s:
        from app.models import NearbyCache

        row = s.query(NearbyCache).first()
        assert row is not None
        row.fetched_at = datetime.utcnow() - timedelta(days=8)
        s.commit()
    r = client.get("/api/nearby")
    assert r.json()["from_cache"] is False
    assert len(calls) == 2


def test_nearby_page_needs_home_location():
    client.put(
        "/api/settings",
        json={"home_latitude": "", "home_longitude": "", "home_name": ""},
    )
    r = client.get("/api/nearby")
    assert r.json()["error"] == "no_home_location"
    r = client.get("/nearby")
    assert r.status_code == 200
    assert "Set your home location" in r.text
    _set_home()  # restore for other tests


def test_nearby_page_renders_cards(monkeypatch):
    monkeypatch.setattr(
        nearby_mod, "fetch_nearby_observations", lambda lat, lng: CANNED_NEARBY
    )
    # bust the cache so the page fetches fresh
    with SessionLocal() as s:
        from app.models import NearbyCache

        for row in s.query(NearbyCache).all():
            s.delete(row)
        s.commit()
    r = client.get("/nearby")
    assert r.status_code == 200
    assert "American Robin" in r.text
    assert "2 recent nearby observations" in r.text
    assert "＋ Log it" in r.text
    assert "＋ Wishlist" in r.text


def test_home_settings_validation():
    r = client.put("/api/settings", json={"home_latitude": "not-a-number"})
    assert r.status_code == 400
    r = client.put("/api/settings", json={"home_latitude": "999"})
    assert r.status_code == 400
    r = client.put("/api/settings", json={"home_longitude": "-200"})
    assert r.status_code == 400


def test_nearby_rejects_bad_location_directly():
    with SessionLocal() as s:
        assert nearby_mod.get_nearby(s, 999, 0)["error"] == "bad_location"


# ---------------------------------------------------------------------------
# 4. Wishlist
# ---------------------------------------------------------------------------

CANNED_TAXON = {
    "id": 30,
    "common_name": "Painted Bunting",
    "scientific_name": "Passerina ciris",
    "photo_url": "https://example.com/bunting.jpg",
}


def _add_wish(**kw):
    payload = {"scientific_name": "Passerina ciris", "common_name": "Painted Bunting"}
    payload.update(kw)
    r = client.post("/api/wishlist", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_wishlist_add_list_remove():
    item = _add_wish(notes="dream bird")
    assert item["notes"] == "dream bird"
    assert item["seen"] is False
    r = client.get("/api/wishlist")
    assert any(w["id"] == item["id"] for w in r.json()["wishlist"])
    # duplicate scientific name is rejected
    r = client.post("/api/wishlist", json={"scientific_name": "Passerina ciris"})
    assert r.status_code == 409
    # remove
    r = client.delete(f"/api/wishlist/{item['id']}")
    assert r.status_code == 200
    r = client.get("/api/wishlist")
    assert not any(w["id"] == item["id"] for w in r.json()["wishlist"])


def test_wishlist_seen_badge_derived_at_read():
    item = _add_wish()
    r = client.get("/api/wishlist")
    me = next(w for w in r.json()["wishlist"] if w["id"] == item["id"])
    assert me["seen"] is False
    # log the species -> badge appears with no write to the wishlist row
    _log({"species_name": "Painted Bunting", "scientific_name": "Passerina ciris"})
    r = client.get("/api/wishlist")
    me = next(w for w in r.json()["wishlist"] if w["id"] == item["id"])
    assert me["seen"] is True
    client.delete(f"/api/wishlist/{item['id']}")


def test_wishlist_page_renders(monkeypatch):
    _add_wish()
    monkeypatch.setattr(main_mod, "_taxon_info", lambda name: CANNED_TAXON)
    r = client.get("/wishlist")
    assert r.status_code == 200
    assert "Painted Bunting" in r.text
    assert "https://example.com/bunting.jpg" in r.text
    assert "/species/Passerina ciris" in r.text
    # network failure must not break the page
    def _boom(name):
        raise RuntimeError("no network")

    monkeypatch.setattr(main_mod, "_taxon_info", _boom)
    r = client.get("/wishlist")
    assert r.status_code == 200
    assert "Painted Bunting" in r.text
    for w in client.get("/api/wishlist").json()["wishlist"]:
        client.delete(f"/api/wishlist/{w['id']}")


# ---------------------------------------------------------------------------
# 5. Offline
# ---------------------------------------------------------------------------


def test_service_worker_served():
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/javascript")
    assert "fauna-v1" in r.text
    assert "/api/" in r.text


def test_layout_registers_sw_and_outbox():
    r = client.get("/")
    assert r.status_code == 200
    assert "serviceWorker.register('/sw.js')" in r.text
    assert "/static/js/outbox.js" in r.text
    assert 'id="outbox-banner"' in r.text
    assert 'id="offline-bar"' in r.text
    assert "You're offline" in r.text


def test_identify_pages_have_offline_notes():
    for url in ("/identify", "/identify-audio"):
        r = client.get(url)
        assert r.status_code == 200
        assert "offline" in r.text.lower()
        assert "needs a connection" in r.text


def test_outbox_js_unit_node():
    """Unit-test the pure outbox helpers (dataUrlToParts, syncEntry) under node."""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        import pytest

        pytest.skip("node not available")
    js = r"""
    const fs = require('fs');
    const src = fs.readFileSync('app/static/js/outbox.js', 'utf8');
    const window = {};
    new Function('window', 'globalThis', src)(window, window);
    const O = window.FaunaOutbox;
    const assert = require('assert');

    // dataUrlToParts
    const parts = O.dataUrlToParts('data:image/png;base64,aGVsbG8=');
    assert.strictEqual(parts.mime, 'image/png');
    assert.strictEqual(parts.base64, 'aGVsbG8=');
    assert.throws(() => O.dataUrlToParts('not-a-data-url'), /bad data URL/);
    assert.throws(() => O.dataUrlToParts('data:image/png,rawbytes'), /bad data URL/);

    (async () => {
      // syncEntry: sighting without photos -> single POST, no photo call
      let posts = [];
      const http = {
        postJson: (url, obj) => { posts.push(['json', url, obj]); return Promise.resolve({ ok: true, body: { id: 7 } }); },
        postPhotos: (id, photos) => { posts.push(['photos', id, photos]); return Promise.resolve({ ok: true, body: { id } }); },
      };
      let body = await O.syncEntry({ payload: { species_name: 'Wren', photo_path: 'pending_x.png' }, photos: [] }, http);
      assert.strictEqual(body.id, 7);
      assert.strictEqual(posts.length, 1);
      assert.strictEqual(posts[0][0], 'json');
      assert.ok(!('photo_path' in posts[0][2]), 'pending photo_path must not ride along');

      // syncEntry: with photos -> POST then photo upload
      posts = [];
      body = await O.syncEntry(
        { payload: { species_name: 'Wren' }, photos: [{ name: 'a.png', dataUrl: 'data:image/png;base64,aGVsbG8=' }] },
        http
      );
      assert.strictEqual(posts.length, 2);
      assert.strictEqual(posts[1][0], 'photos');
      assert.strictEqual(posts[1][1], 7);

      // syncEntry: failed sighting POST -> rejects, no photo attempt
      const bad = {
        postJson: () => Promise.resolve({ ok: false, body: { detail: 'bad' } }),
        postPhotos: () => { throw new Error('should not be called'); },
      };
      await assert.rejects(O.syncEntry({ payload: {}, photos: [] }, bad), /sighting sync failed/);
      console.log('OUTBOX-JS-OK');
    })().catch((e) => { console.error('FAIL', e); process.exit(1); });
    """
    proc = subprocess.run(
        [node, "-e", js], capture_output=True, text=True, timeout=30
    )
    assert "OUTBOX-JS-OK" in proc.stdout, proc.stderr + proc.stdout


def test_json_in_script_blocks_parses_with_quotes():
    """Regression: string data embedded in <script type="application/json">
    must survive as valid JSON (script is raw text; HTML entities don't decode)."""
    import re

    from app import pages as pages_mod

    r = client.get("/map")
    assert r.status_code == 200
    m = re.search(
        r'<script type="application/json" id="map-pins">(.*?)</script>',
        r.text,
        re.DOTALL,
    )
    assert m, "map pins block missing"
    pins = json.loads(m.group(1))
    assert isinstance(pins, list) and len(pins) >= 1
    assert pins[0]["species"] == "Map Robin"
    # the helper itself: quotes and </script> breakouts
    blob = pages_mod._json_script([{"a": 'x"y</script>z'}])
    assert json.loads(blob) == [{"a": 'x"y</script>z'}]
    assert "</script" not in blob


def test_inline_js_parses_on_all_pages():
    """Every inline <script> on every page must be valid JS (node --check).

    Regression: the backup + settings scripts once shipped with an ASCII
    apostrophe inside a single-quoted string, silently killing those blocks.
    """
    import re
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        import pytest

        pytest.skip("node not available")
    urls = [
        "/",
        "/observations",
        "/observations/new",
        "/life-list",
        "/stats",
        "/identify",
        "/identify-audio",
        "/gallery",
        "/import",
        "/settings",
        "/map",
        "/nearby",
        "/wishlist",
    ]
    failures = []
    for url in urls:
        r = client.get(url)
        assert r.status_code == 200, url
        for i, s in enumerate(re.findall(r"<script>(.*?)</script>", r.text, re.DOTALL)):
            if not s.strip():
                continue
            f = TMP / f"audit-{i}.js"
            f.write_text(s)
            proc = subprocess.run(
                [node, "--check", str(f)], capture_output=True, text=True
            )
            if proc.returncode != 0:
                failures.append(f"{url}#{i}: {proc.stderr.strip().splitlines()[-1]}")
    assert not failures, "\n".join(failures)
