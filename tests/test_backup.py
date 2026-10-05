"""Backup endpoint tests: GET /api/backup builds a zip with a live DB snapshot,
all photos, and human-readable JSON dumps.

Run:  cd ~/workspace/fauna && PYTHONPATH=. .venv/bin/python -m pytest -q
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fauna-test-"))
os.environ.setdefault("FAUNA_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("FAUNA_UPLOAD_DIR", str(TMP / "photos"))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app)

FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128


def _seed_observation(species: str, with_photo: bool = False) -> dict:
    r = client.post("/api/observations", json={"species_name": species})
    assert r.status_code == 200, r.text
    obs = r.json()
    if with_photo:
        r = client.post(
            f"/api/observations/{obs['id']}/photo",
            files={"file": ("robin.png", FAKE_PNG, "image/png")},
        )
        assert r.status_code == 200, r.text
        obs = r.json()
    return obs


def test_backup_zip_contents():
    obs_photo = _seed_observation("American Robin", with_photo=True)
    _seed_observation("Eastern Gray Squirrel")

    r = client.get("/api/backup")
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/zip"
    assert "fauna-backup-" in r.headers["content-disposition"]

    out = TMP / "backup.zip"
    out.write_bytes(r.content)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()

    for expected in ("fauna.db", "observations.json", "settings.json", "README.txt"):
        assert expected in names, f"{expected} missing from backup"

    # photos/ holds the uploaded image bytes
    photo_entries = [n for n in names if n.startswith("photos/")]
    assert len(photo_entries) == 1, photo_entries
    with zipfile.ZipFile(out) as zf:
        photo_bytes = zf.read(photo_entries[0])
    assert photo_bytes == FAKE_PNG
    assert photo_entries[0].endswith(Path(obs_photo["photo_url"]).name)

    # fauna.db is a consistent snapshot: both sightings present
    with zipfile.ZipFile(out) as zf:
        zf.extract("fauna.db", TMP / "extracted")
    conn = sqlite3.connect(TMP / "extracted" / "fauna.db")
    rows = conn.execute(
        "SELECT species_name FROM observations ORDER BY id"
    ).fetchall()
    conn.close()
    species = {row[0] for row in rows}
    assert "American Robin" in species
    assert "Eastern Gray Squirrel" in species

    # observations.json parses with both entries, API-dict shape
    with zipfile.ZipFile(out) as zf:
        dump = json.loads(zf.read("observations.json"))
    assert len(dump["observations"]) == 2
    robin = next(
        o for o in dump["observations"] if o["species_name"] == "American Robin"
    )
    assert robin["photo_url"].startswith("/photos/")

    # settings.json parses and never leaks secret values
    with zipfile.ZipFile(out) as zf:
        settings = json.loads(zf.read("settings.json"))
    assert "openrouter_api_key" in settings
    assert settings["openrouter_api_key"] in (None, "<configured>")

    # README.txt explains restore
    with zipfile.ZipFile(out) as zf:
        readme = zf.read("README.txt").decode("utf-8")
    assert "restore" in readme.lower()

    # live DB still works after VACUUM INTO
    r = client.get("/api/observations")
    assert r.status_code == 200
    assert len(r.json()["observations"]) == 2
