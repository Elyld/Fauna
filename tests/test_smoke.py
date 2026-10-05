"""Smoke tests: boot the app, hit /health, round-trip an observation.

Run:  cd ~/workspace/fauna && PYTHONPATH=. .venv/bin/python -m pytest -q
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fauna-test-"))
os.environ.setdefault("FAUNA_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("FAUNA_UPLOAD_DIR", str(TMP / "photos"))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import UPLOAD_DIR, init_db  # noqa: E402
from app.main import app  # noqa: E402

assert UPLOAD_DIR  # keep the conventional import used

init_db()
client = TestClient(app)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["version"] == "0.1.0"


def test_observation_round_trip():
    payload = {
        "species_name": "Eastern Gray Squirrel",
        "scientific_name": "Sciurus carolinensis",
        "count": 2,
        "location_name": "Backyard oak",
        "notes": "Chasing each other around the trunk.",
    }
    r = client.post("/api/observations", json=payload)
    assert r.status_code == 200, r.text
    created = r.json()
    assert created["id"]
    assert created["species_name"] == "Eastern Gray Squirrel"

    r = client.get(f"/api/observations/{created['id']}")
    assert r.status_code == 200
    assert r.json()["scientific_name"] == "Sciurus carolinensis"

    r = client.get("/api/observations")
    assert r.status_code == 200
    assert any(o["id"] == created["id"] for o in r.json()["observations"])


def test_photo_upload():
    r = client.post("/api/observations", json={"species_name": "Test Bunny"})
    obs_id = r.json()["id"]
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    r = client.post(
        f"/api/observations/{obs_id}/photo",
        files={"file": ("bunny.png", fake_png, "image/png")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["photo_url"] and body["photo_url"].startswith("/photos/")

    r = client.delete(f"/api/observations/{obs_id}")
    assert r.status_code == 200
    assert r.json()["deleted"] == obs_id


def test_delete_removes_photo_file():
    r = client.post("/api/observations", json={"species_name": "Test Mole"})
    obs_id = r.json()["id"]
    fake_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
    r = client.post(
        f"/api/observations/{obs_id}/photo",
        files={"file": ("mole.png", fake_png, "image/png")},
    )
    assert r.status_code == 200, r.text
    photo_url = r.json()["photo_url"]
    photo_file = UPLOAD_DIR / Path(photo_url).name
    assert photo_file.exists()

    r = client.delete(f"/api/observations/{obs_id}")
    assert r.status_code == 200
    assert not photo_file.exists(), "photo file orphaned after delete"
