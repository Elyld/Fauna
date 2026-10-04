"""Tests for vision-model photo ID (app/vision_id.py + /api/identify wiring).

The OpenRouter HTTP call is always mocked (no network, no key needed).
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fauna-vision-test-"))
os.environ.setdefault("FAUNA_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("FAUNA_UPLOAD_DIR", str(TMP / "photos"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import vision_id  # noqa: E402
from app.database import UPLOAD_DIR, init_db  # noqa: E402
from app.main import app  # noqa: E402

assert UPLOAD_DIR

init_db()
client = TestClient(app)

FAKE_JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 128

VISION_CONTENT = (
    '[{"common_name": "Eastern Gray Squirrel", '
    '"scientific_name": "Sciurus carolinensis", "confidence": 0.92, '
    '"notes": "Bushy tail and gray coat visible."},'
    '{"common_name": "Fox Squirrel", "scientific_name": "Sciurus niger", '
    '"confidence": 0.31, "notes": "Similar shape, less likely."}]'
)


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def _fake_post(content, status=200, seen=None):
    def _post(url, json=None, headers=None, timeout=None):
        if seen is not None:
            seen.update({"url": url, "json": json, "headers": headers})
        return _FakeResp(status, {"choices": [{"message": {"content": content}}]})

    return _post


# --- JSON extraction -------------------------------------------------------

def test_extract_plain_array():
    assert vision_id._extract_json_array('[{"a": 1}]') == [{"a": 1}]


def test_extract_fenced_json():
    text = 'Here you go:\n```json\n[{"common_name": "Robin"}]\n```'
    assert vision_id._extract_json_array(text) == [{"common_name": "Robin"}]


def test_extract_prose_wrapped():
    text = 'I see an animal. [{"common_name": "Robin"}] Hope that helps!'
    assert vision_id._extract_json_array(text) == [{"common_name": "Robin"}]


def test_extract_rejects_garbage():
    with pytest.raises(Exception):
        vision_id._extract_json_array("just some words, no json here")


# --- identify_with_vision ---------------------------------------------------

def test_identify_parses_candidates_and_request_shape(monkeypatch):
    seen = {}
    monkeypatch.setattr(vision_id.httpx, "post", _fake_post(VISION_CONTENT, seen=seen))
    results = vision_id.identify_with_vision(b"img-bytes", "squirrel.jpg", api_key="sk-test", model="test/model:free")
    assert len(results) == 2
    assert results[0]["common_name"] == "Eastern Gray Squirrel"
    assert results[0]["scientific_name"] == "Sciurus carolinensis"
    assert results[0]["confidence"] == 0.92
    assert "Bushy tail" in results[0]["notes"]

    # Request shape against OpenRouter's chat-completions contract.
    assert seen["url"] == vision_id.OPENROUTER_URL
    assert seen["json"]["model"] == "test/model:free"
    assert seen["headers"]["Authorization"] == "Bearer sk-test"
    user_parts = seen["json"]["messages"][1]["content"]
    img = next(p for p in user_parts if p["type"] == "image_url")
    assert img["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_identify_no_key(monkeypatch):
    with pytest.raises(vision_id.VisionIDError) as excinfo:
        vision_id.identify_with_vision(b"img", api_key=None)
    assert excinfo.value.reason == "no_key"


def test_identify_api_error_status(monkeypatch):
    monkeypatch.setattr(vision_id.httpx, "post", _fake_post("oops", status=500))
    with pytest.raises(vision_id.VisionIDError) as excinfo:
        vision_id.identify_with_vision(b"img", api_key="sk-test")
    assert excinfo.value.reason == "api_error"


def test_identify_api_error_transport(monkeypatch):
    import httpx as _httpx

    def _boom(*a, **k):
        raise _httpx.ConnectError("net down")

    monkeypatch.setattr(vision_id.httpx, "post", _boom)
    with pytest.raises(vision_id.VisionIDError) as excinfo:
        vision_id.identify_with_vision(b"img", api_key="sk-test")
    assert excinfo.value.reason == "api_error"


def test_identify_parse_failed(monkeypatch):
    monkeypatch.setattr(vision_id.httpx, "post", _fake_post("definitely not json {{{"))
    with pytest.raises(vision_id.VisionIDError) as excinfo:
        vision_id.identify_with_vision(b"img", api_key="sk-test")
    assert excinfo.value.reason == "parse_failed"


def test_identify_no_animal(monkeypatch):
    monkeypatch.setattr(vision_id.httpx, "post", _fake_post("[]"))
    with pytest.raises(vision_id.VisionIDError) as excinfo:
        vision_id.identify_with_vision(b"img", api_key="sk-test")
    assert excinfo.value.reason == "no_animal"


def test_identify_confidence_clamped_and_blank_names_skipped(monkeypatch):
    content = (
        '[{"common_name": "X", "scientific_name": "Y y", "confidence": 9.9},'
        '{"common_name": "", "scientific_name": ""},'
        '{"common_name": "Only Common", "confidence": "high"}]'
    )
    monkeypatch.setattr(vision_id.httpx, "post", _fake_post(content))
    results = vision_id.identify_with_vision(b"img", api_key="sk-test")
    assert len(results) == 2
    assert results[0]["confidence"] == 1.0  # clamped
    assert results[1]["confidence"] == 0.5  # unparseable -> default
    assert results[1]["scientific_name"] is None


# --- enrichment + /api/identify wiring --------------------------------------

FAKE_TAXA = [
    {
        "id": 46017,
        "common_name": "Eastern Gray Squirrel",
        "scientific_name": "Sciurus carolinensis",
        "rank": "species",
        "photo_url": "https://example.com/squirrel-medium.jpg",
    }
]


def _set_settings(key=None, model=None):
    payload = {}
    if key is not None:
        payload["openrouter_api_key"] = key
    if model is not None:
        payload["vision_model"] = model
    r = client.put("/api/settings", json=payload)
    assert r.status_code == 200, r.text


def _upload():
    return client.post("/api/identify", files={"file": ("squirrel.jpg", FAKE_JPG, "image/jpeg")})


def test_enrich_candidate_merges_inat_taxon(monkeypatch):
    import app.main as main_mod

    monkeypatch.setattr(main_mod.inat, "search_taxa", lambda q, per_page=3: FAKE_TAXA)
    card = main_mod._enrich_vision_candidate(
        {"common_name": "Eastern Gray Squirrel", "scientific_name": "Sciurus carolinensis",
         "confidence": 0.92, "notes": "Bushy tail."}
    )
    # Same card shape the /identify UI already renders.
    assert card["taxon_id"] == 46017
    assert card["common_name"] == "Eastern Gray Squirrel"
    assert card["scientific_name"] == "Sciurus carolinensis"
    assert card["combined_score"] == 0.92
    assert card["photo_url"] == "https://example.com/squirrel-medium.jpg"


def test_enrich_candidate_survives_inat_outage(monkeypatch):
    import app.main as main_mod
    import httpx as _httpx

    def _boom(q, per_page=3):
        raise _httpx.ConnectError("down")

    monkeypatch.setattr(main_mod.inat, "search_taxa", _boom)
    card = main_mod._enrich_vision_candidate(
        {"common_name": "Mystery Bird", "scientific_name": None, "confidence": 0.4, "notes": None}
    )
    assert card["taxon_id"] is None
    assert card["common_name"] == "Mystery Bird"
    assert card["combined_score"] == 0.4
    assert card["photo_url"] is None


def test_api_identify_uses_vision_when_key_set(monkeypatch):
    import app.main as main_mod

    _set_settings(key="sk-test-key", model="test/model:free")
    called = {}

    def _fake_vision(image_bytes, filename="photo.jpg", api_key=None, model=None):
        called.update({"api_key": api_key, "model": model, "nbytes": len(image_bytes)})
        return [{"common_name": "Eastern Gray Squirrel",
                 "scientific_name": "Sciurus carolinensis",
                 "confidence": 0.9, "notes": None}]

    def _no_inat(*a, **k):
        raise AssertionError("legacy iNat CV path must not run when vision key is set")

    monkeypatch.setattr(main_mod.vision_id, "identify_with_vision", _fake_vision)
    monkeypatch.setattr(main_mod.inat, "identify_image", _no_inat)
    monkeypatch.setattr(main_mod.inat, "search_taxa", lambda q, per_page=3: FAKE_TAXA)

    r = _upload()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    assert len(body["suggestions"]) == 1
    assert body["suggestions"][0]["scientific_name"] == "Sciurus carolinensis"
    assert body["suggestions"][0]["combined_score"] == 0.9
    assert called["api_key"] == "sk-test-key"
    assert called["model"] == "test/model:free"
    assert called["nbytes"] > 0


def test_api_identify_falls_back_to_inat_token(monkeypatch):
    import app.main as main_mod

    _set_settings(key="")  # clear the key
    monkeypatch.setenv("INAT_API_TOKEN", "dummy-token")

    def _no_vision(*a, **k):
        raise AssertionError("vision path must not run without a key")

    monkeypatch.setattr(main_mod.vision_id, "identify_with_vision", _no_vision)
    monkeypatch.setattr(
        main_mod.inat, "identify_image",
        lambda *a, **k: [{"taxon_id": 1, "common_name": "Robin", "combined_score": 0.8}],
    )
    r = _upload()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    assert body["suggestions"][0]["common_name"] == "Robin"


def test_api_identify_not_connected_without_either(monkeypatch):
    import app.main as main_mod

    _set_settings(key="")
    monkeypatch.delenv("INAT_API_TOKEN", raising=False)
    r = _upload()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggestions"] == []
    assert body["error"] == "not_connected"
    assert (UPLOAD_DIR / body["pending_photo"]).exists()


def test_api_identify_vision_failure_maps_to_friendly_error(monkeypatch):
    import app.main as main_mod

    _set_settings(key="sk-test-key")

    def _boom(*a, **k):
        raise vision_id.VisionIDError("no_animal")

    monkeypatch.setattr(main_mod.vision_id, "identify_with_vision", _boom)
    r = _upload()
    assert r.status_code == 200, r.text
    assert r.json()["error"] == "no_animal_found"


# --- settings API + page -----------------------------------------------------

def test_settings_round_trip_never_leaks_key():
    r = client.put("/api/settings", json={"openrouter_api_key": "sk-super-secret", "vision_model": "custom/model:free"})
    assert r.status_code == 200, r.text
    body = client.get("/api/settings").json()
    assert body["vision_model"] == "custom/model:free"
    assert body["openrouter_api_key_configured"] is True
    assert "sk-super-secret" not in str(body)
    # The key itself authenticates the vision path (proves it was stored).
    import app.main as main_mod
    from app.database import SessionLocal

    with SessionLocal() as s:
        assert main_mod.get_setting(s, "openrouter_api_key") == "sk-super-secret"
    # Clearing works and flips the flag.
    client.put("/api/settings", json={"openrouter_api_key": ""})
    body = client.get("/api/settings").json()
    assert body["openrouter_api_key_configured"] is False


def test_settings_page_renders():
    r = client.get("/settings")
    assert r.status_code == 200
    assert "OpenRouter API key" in r.text
    assert "Vision model" in r.text
    # The key value itself must never be rendered into the page.
    assert "sk-super-secret" not in r.text


def test_nav_links_settings():
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/settings"' in r.text
