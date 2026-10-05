"""OpenRouter vision-model catalog: GET /api/openrouter-models returns only
vision-capable models with free flags, cached 24h. The Settings dropdown
falls back to a plain text field when the catalog is unreachable.

Run:  cd ~/workspace/fauna && PYTHONPATH=. .venv/bin/python -m pytest -q
"""
from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fauna-test-"))
os.environ.setdefault("FAUNA_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("FAUNA_UPLOAD_DIR", str(TMP / "photos"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import openrouter_models as orm  # noqa: E402
from app.database import init_db  # noqa: E402
from app.main import app  # noqa: E402

init_db()
client = TestClient(app)


@pytest.fixture(autouse=True)
def _clear_cache():
    orm.clear_cache()
    yield
    orm.clear_cache()


FAKE_CATALOG = {
    "data": [
        {
            "id": "google/gemma-4-31b-it:free",
            "name": "Gemma 4 31B",
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["image", "text"]},
        },
        {
            "id": "openai/gpt-4o-mini",
            "name": "GPT-4o mini",
            "pricing": {"prompt": "0.00000015", "completion": "0.0000006"},
            "architecture": {"input_modalities": ["image", "text"]},
        },
        {
            "id": "meta/llama-4-maverick:free",
            "name": "Llama 4 Maverick",
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text"]},  # not vision!
        },
        {
            "id": "deepseek/deepseek-chat",
            "name": "DeepSeek Chat",
            "pricing": {"prompt": "0.00000027", "completion": "0.0000011"},
            "architecture": {"input_modalities": ["text"]},  # not vision!
        },
    ]
}


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeHttpx:
    def __init__(self):
        self.calls = 0

    def get(self, url, **kwargs):
        self.calls += 1
        assert url == orm.MODELS_URL
        return _FakeResp(FAKE_CATALOG)


def test_endpoint_returns_vision_models_only(monkeypatch):
    fake = _FakeHttpx()
    monkeypatch.setattr(orm, "httpx", fake)
    r = client.get("/api/openrouter-models")
    assert r.status_code == 200
    models = r.json()["models"]
    ids = [m["id"] for m in models]
    # Only the two image-capable models survive the vision filter.
    assert ids == ["google/gemma-4-31b-it:free", "openai/gpt-4o-mini"]
    by_id = {m["id"]: m for m in models}
    assert by_id["google/gemma-4-31b-it:free"]["free"] is True
    assert by_id["openai/gpt-4o-mini"]["free"] is False
    assert by_id["google/gemma-4-31b-it:free"]["name"] == "Gemma 4 31B"


def test_cache_24h_second_call_does_not_refetch(monkeypatch):
    fake = _FakeHttpx()
    monkeypatch.setattr(orm, "httpx", fake)
    client.get("/api/openrouter-models")
    client.get("/api/openrouter-models")
    assert fake.calls == 1
    # Force expiry: an old timestamp refetches.
    orm._cache["at"] = time.time() - orm.CACHE_TTL - 1
    client.get("/api/openrouter-models")
    assert fake.calls == 2


def test_endpoint_never_raises_on_failure(monkeypatch):
    class _Boom:
        def get(self, url, **kwargs):
            raise RuntimeError("openrouter is down")

    monkeypatch.setattr(orm, "httpx", _Boom())
    r = client.get("/api/openrouter-models")
    assert r.status_code == 200
    assert r.json() == {"models": []}


def test_free_flag_from_pricing_fields(monkeypatch):
    # A model without the :free suffix but zero pricing is still free.
    fake = _FakeHttpx()
    monkeypatch.setattr(orm, "httpx", fake)
    orm.get_vision_models()
    assert orm.is_free({"id": "x/y", "pricing": {"prompt": "0", "completion": "0"}})
    assert not orm.is_free({"id": "x/y", "pricing": {"prompt": "0.1", "completion": "0"}})
    assert not orm.is_free({"id": "x/y"})  # missing pricing -> not free


def test_custom_value_round_trips_through_settings():
    r = client.put("/api/settings", json={"vision_model": "some/future-model:free"})
    assert r.status_code == 200
    r = client.get("/api/settings")
    assert r.json()["vision_model"] == "some/future-model:free"
    # The settings page renders the saved value into the text field, so the
    # dropdown JS can fall back to "Custom…" when it's not in the catalog.
    r = client.get("/settings")
    assert r.status_code == 200
    assert 'value="some/future-model:free"' in r.text
    assert 'id="vision-model-select"' in r.text
    assert 'id="vision-model-free-only"' in r.text
    # Permissive validation: any non-empty id is accepted.
    r = client.put("/api/settings", json={"vision_model": "  "})
    assert r.status_code == 200
    r = client.put("/api/settings", json={"vision_model": "google/gemma-4-31b-it:free"})
    assert r.json()["vision_model"] == "google/gemma-4-31b-it:free"
