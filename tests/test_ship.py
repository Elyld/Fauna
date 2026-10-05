"""Ship-readiness regression tests: mobile tab bar, backup contents.

Run:  cd ~/workspace/fauna && PYTHONPATH=. .venv/bin/python -m pytest -q
"""
from __future__ import annotations

import io
import os
import tempfile
import zipfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fauna-test-ship-"))
os.environ.setdefault("FAUNA_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("FAUNA_UPLOAD_DIR", str(TMP / "photos"))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app)


def test_mobile_tabbar_has_settings():
    """The bottom tab bar (mobile) must include a Settings tab."""
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert '<nav class="tabbar"' in body
    for href in ("/", "/observations", "/map", "/identify", "/identify-audio", "/settings"):
        assert f'<a href="{href}"' in body, f"tab bar missing {href}"


def test_tabbar_on_every_page():
    """No page may strand a mobile user without the tab bar."""
    for path in [
        "/", "/observations", "/observations/new", "/life-list", "/map",
        "/nearby", "/wishlist", "/stats", "/identify", "/identify-audio",
        "/gallery", "/import", "/settings",
    ]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert '<nav class="tabbar"' in r.text, f"no tab bar on {path}"


def test_backup_includes_wishlist_json():
    """Backup zip contains wishlist.json with serializable datetimes."""
    client.post(
        "/api/wishlist",
        json={"scientific_name": "Testus shipus", "common_name": "Ship Testbird"},
    )
    r = client.get("/api/backup")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert "wishlist.json" in names
    assert "observations.json" in names
    assert "fauna.db" in names
    import json

    wl = json.loads(zf.read("wishlist.json"))
    assert any(w["scientific_name"] == "Testus shipus" for w in wl["wishlist"])
    assert "README.txt" in names
    assert b"wishlist" in zf.read("README.txt").lower()


def test_backup_readme_mentions_restore_of_photos_and_wishlist():
    r = client.get("/api/backup")
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    readme = zf.read("README.txt").decode()
    assert "photos" in readme.lower()
    assert "wishlist" in readme.lower()
    assert "replace" in readme.lower()  # restore steps present
