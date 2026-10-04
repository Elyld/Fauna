"""Tests for photo ID (/api/identify, /identify page, confirm-to-observation flow).

The iNaturalist HTTP call is mocked (no network). A live check runs only
with FAUNA_LIVE_TESTS=1 *and* a real INAT_API_TOKEN in the environment.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fauna-test-"))
os.environ.setdefault("FAUNA_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("FAUNA_UPLOAD_DIR", str(TMP / "photos"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import inat  # noqa: E402
from app.database import UPLOAD_DIR, init_db  # noqa: E402
from app.main import app  # noqa: E402

assert UPLOAD_DIR

init_db()
client = TestClient(app)

FAKE_CV_JSON = {
    "total_results": 2,
    "page": 1,
    "per_page": 2,
    "results": [
        {
            "vision_score": 0.96,
            "combined_score": 0.93,
            "frequency_score": 1,
            "taxon": {
                "id": 46017,
                "name": "Sciurus carolinensis",
                "preferred_common_name": "Eastern Gray Squirrel",
                "rank": "species",
                "default_photo": {
                    "medium_url": "https://example.com/squirrel-medium.jpg",
                    "square_url": "https://example.com/squirrel-square.jpg",
                },
            },
        },
        {
            "vision_score": 0.71,
            "combined_score": 0.68,
            "frequency_score": 1,
            "taxon": {
                "id": 46019,
                "name": "Sciurus niger",
                "preferred_common_name": "Fox Squirrel",
                "rank": "species",
                "default_photo": {
                    "medium_url": "https://example.com/fox-medium.jpg",
                },
            },
        },
    ],
}


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _fake_post_ok(url, files=None, data=None, headers=None, timeout=None):
    assert url.endswith("/computervision/score_image")
    assert headers and headers["Authorization"].startswith("Bearer ")
    assert files and "image" in files
    return _FakeResp(200, FAKE_CV_JSON)


def test_identify_image_parses_cv_response(monkeypatch):
    monkeypatch.setenv("INAT_API_TOKEN", "dummy-token")
    monkeypatch.setattr(inat.httpx, "post", _fake_post_ok)
    suggestions = inat.identify_image(b"fake-bytes", "squirrel.jpg")
    assert len(suggestions) == 2
    first = suggestions[0]
    assert first["taxon_id"] == 46017
    assert first["common_name"] == "Eastern Gray Squirrel"
    assert first["scientific_name"] == "Sciurus carolinensis"
    assert first["rank"] == "species"
    assert first["vision_score"] == 0.96
    assert first["combined_score"] == 0.93
    assert first["photo_url"] == "https://example.com/squirrel-medium.jpg"
    # best guess first
    assert suggestions[1]["common_name"] == "Fox Squirrel"


def test_identify_image_no_token(monkeypatch):
    monkeypatch.setattr(inat, "get_api_token", lambda: None)
    with pytest.raises(inat.INatAuthError) as excinfo:
        inat.identify_image(b"fake-bytes")
    assert excinfo.value.reason == "no_token"


def test_identify_image_rejected_token(monkeypatch):
    monkeypatch.setenv("INAT_API_TOKEN", "stale-token")
    monkeypatch.setattr(inat.httpx, "post", lambda *a, **k: _FakeResp(401))
    with pytest.raises(inat.INatAuthError) as excinfo:
        inat.identify_image(b"fake-bytes")
    assert excinfo.value.reason == "rejected"


CANNED = [
    {
        "taxon_id": 46017,
        "common_name": "Eastern Gray Squirrel",
        "scientific_name": "Sciurus carolinensis",
        "rank": "species",
        "vision_score": 0.96,
        "combined_score": 0.93,
        "photo_url": "https://example.com/squirrel-medium.jpg",
    }
]

FAKE_JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 128


def _upload_identify():
    return client.post("/api/identify", files={"file": ("squirrel.jpg", FAKE_JPG, "image/jpeg")})


def test_api_identify_returns_suggestions_and_pending_photo(monkeypatch):
    import app.main as main_mod

    monkeypatch.setattr(main_mod.inat, "identify_image", lambda *a, **k: CANNED)
    r = _upload_identify()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    assert body["suggestions"] == CANNED
    assert body["pending_photo"].startswith("pending_")
    assert body["photo_url"] == f"/photos/{body['pending_photo']}"
    assert (UPLOAD_DIR / body["pending_photo"]).exists()


def test_api_identify_not_connected_still_saves_photo(monkeypatch):
    import app.main as main_mod

    def _boom(*a, **k):
        raise inat.INatAuthError("no_token")

    monkeypatch.setattr(main_mod.inat, "identify_image", _boom)
    r = _upload_identify()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggestions"] == []
    assert body["error"] == "not_connected"
    # The photo is still kept so she can log the sighting manually.
    assert (UPLOAD_DIR / body["pending_photo"]).exists()


def test_api_identify_rejects_bad_type():
    r = client.post(
        "/api/identify", files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    assert r.status_code == 400


def test_confirm_flow_claims_pending_photo_and_needs_id(monkeypatch):
    import app.main as main_mod

    monkeypatch.setattr(main_mod.inat, "identify_image", lambda *a, **k: CANNED)
    pending = _upload_identify().json()["pending_photo"]

    r = client.post(
        "/api/observations",
        json={
            "species_name": "Eastern Gray Squirrel",
            "scientific_name": "Sciurus carolinensis",
            "count": 1,
            "photo_path": pending,
            "needs_id": True,
            "notes": "Confirming from the Identify flow.",
        },
    )
    assert r.status_code == 200, r.text
    obs = r.json()
    # Pending file was claimed and renamed to a permanent name.
    assert obs["photo_path"] != pending
    assert not obs["photo_path"].startswith("pending_")
    assert not (UPLOAD_DIR / pending).exists()
    assert (UPLOAD_DIR / obs["photo_path"]).exists()
    assert obs["photo_url"] == f"/photos/{obs['photo_path']}"
    assert obs["needs_id"] is True

    # Path traversal attempts are rejected, not honored.
    r = client.post(
        "/api/observations",
        json={"species_name": "Sneaky", "photo_path": "../../etc/passwd"},
    )
    assert r.status_code == 400


def test_identify_page_renders():
    r = client.get("/identify")
    assert r.status_code == 200
    html = r.text
    assert "What did I see?" in html
    assert "/api/identify" in html
    assert "None of these" in html


def test_nav_links_identify():
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/identify"' in r.text
    assert "What did I see?" in r.text


def test_new_observation_prefill():
    r = client.get(
        "/observations/new",
        params={"species_name": "Eastern Gray Squirrel", "needs_id": "1"},
    )
    assert r.status_code == 200
    assert 'value="Eastern Gray Squirrel"' in r.text
    assert "I'm not sure what this is" in r.text
    assert "checked" in r.text


LIVE = pytest.mark.skipif(
    os.environ.get("FAUNA_LIVE_TESTS") != "1" or not os.environ.get("INAT_API_TOKEN"),
    reason="live-network test; needs FAUNA_LIVE_TESTS=1 and INAT_API_TOKEN",
)


@LIVE
def test_identify_live_squirrel_photo():
    # Sandbox-only proxy workaround (same as test_inat_live.py).
    for _var in ("NO_PROXY", "no_proxy"):
        _val = os.environ.get(_var)
        if _val:
            os.environ[_var] = ",".join(p for p in _val.split(",") if "[" not in p)
    demo = sorted(Path("photos").glob("*.jp*g"))
    assert demo, "need a demo photo to score"
    suggestions = inat.identify_image(demo[0].read_bytes(), demo[0].name)
    assert suggestions, "expected at least one suggestion"
    assert suggestions[0]["scientific_name"]
    print("top live suggestion:", suggestions[0])
