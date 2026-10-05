"""Quality-of-life batch: life list, stats, search/filter, edit, CSV export.

Run:  cd ~/workspace/fauna && PYTHONPATH=. .venv/bin/python -m pytest -q
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fauna-test-qol-"))
os.environ.setdefault("FAUNA_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("FAUNA_UPLOAD_DIR", str(TMP / "photos"))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import UPLOAD_DIR, init_db  # noqa: E402
from app.main import app  # noqa: E402

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


def test_life_list_aggregation():
    _log("QoL Squirrel", scientific_name="Sciurus carolinensis", count=3,
         observed_at=(BASE - timedelta(days=10)).isoformat())
    _log("QoL Squirrel", scientific_name="Sciurus carolinensis", count=2,
         observed_at=BASE.isoformat())
    _log("QoL Robin", scientific_name="Turdus migratorius",
         observed_at=(BASE - timedelta(days=5)).isoformat())

    r = client.get("/life-list")
    assert r.status_code == 200
    html = r.text
    assert "QoL Squirrel" in html
    assert "QoL Robin" in html
    assert "2 sightings" in html  # squirrel logged twice
    assert "Sciurus carolinensis" in html

    # alphabetical sort puts QoL Robin before QoL Squirrel
    r = client.get("/life-list?sort=alpha")
    assert r.status_code == 200
    assert r.text.index("QoL Robin") < r.text.index("QoL Squirrel")

    # most-seen sort puts the twice-logged squirrel first
    r = client.get("/life-list?sort=most")
    assert r.status_code == 200
    assert r.text.index("QoL Squirrel") < r.text.index("QoL Robin")

    # bad sort value falls back to recent without erroring
    r = client.get("/life-list?sort=bogus")
    assert r.status_code == 200


def test_search_and_needs_id_filter():
    _log("QoL Searchbird", location_name="Old Oak Hollow", notes="sang at dawn")
    _log("QoL Mystery", needs_id=True, location_name="Foggy Field")

    r = client.get("/observations?q=oak+hollow")
    assert r.status_code == 200
    assert "QoL Searchbird" in r.text

    r = client.get("/observations?q=dawn")
    assert r.status_code == 200
    assert "QoL Searchbird" in r.text  # notes are searchable

    r = client.get("/observations?needs_id=true")
    assert r.status_code == 200
    assert "QoL Mystery" in r.text
    assert "QoL Searchbird" not in r.text

    # same params on the JSON API
    r = client.get("/api/observations", params={"q": "Searchbird"})
    assert r.status_code == 200
    names = [o["species_name"] for o in r.json()["observations"]]
    assert "QoL Searchbird" in names
    r = client.get("/api/observations", params={"needs_id": "true"})
    assert r.status_code == 200
    assert all(o["needs_id"] for o in r.json()["observations"])


def test_edit_observation():
    obs = _log("QoL Editable", notes="before", count=1)
    oid = obs["id"]

    r = client.get(f"/observations/{oid}/edit")
    assert r.status_code == 200
    assert "Edit sighting" in r.text
    assert "QoL Editable" in r.text

    r = client.put(f"/api/observations/{oid}", json={"notes": "after", "count": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["notes"] == "after"
    assert body["count"] == 5
    assert body["species_name"] == "QoL Editable"  # untouched fields preserved

    r = client.get(f"/observations/{oid}/edit")
    assert "after" in r.text  # prefilled with the new notes

    r = client.put("/api/observations/999999", json={"notes": "x"})
    assert r.status_code == 404
    r = client.get("/observations/999999/edit")
    assert r.status_code == 404


def test_csv_export():
    _log("QoL Csvbird", scientific_name="Csvus birdus", count=2)
    r = client.get("/api/observations/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "fauna-observations.csv" in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    header = lines[0].split(",")
    assert header[:4] == ["id", "species_name", "scientific_name", "count"]
    assert any("QoL Csvbird" in line for line in lines[1:])


def test_stats_page_renders():
    r = client.get("/stats")
    assert r.status_code == 200
    assert "Sightings per month" in r.text
    assert "heat-cell" in r.text
    # nav links present
    assert "/life-list" in r.text
