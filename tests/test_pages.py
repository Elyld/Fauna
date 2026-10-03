"""HTML page smoke checks: the three UI pages render."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fauna-pages-test-"))
os.environ.setdefault("FAUNA_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("FAUNA_UPLOAD_DIR", str(TMP / "photos"))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import UPLOAD_DIR, init_db  # noqa: E402
from app.main import app  # noqa: E402

assert UPLOAD_DIR

init_db()
client = TestClient(app)


def test_home_page():
    r = client.get("/")
    assert r.status_code == 200, r.text
    assert "text/html" in r.headers["content-type"]
    assert "theme.css" in r.text
    assert "observations" in r.text


def test_observations_page():
    client.post("/api/observations", json={"species_name": "Page Test Squirrel"})
    r = client.get("/observations")
    assert r.status_code == 200, r.text
    assert "Page Test Squirrel" in r.text


def test_new_observation_page():
    r = client.get("/observations/new")
    assert r.status_code == 200, r.text
    assert "/api/species/search" in r.text
    assert "Log a sighting" in r.text
