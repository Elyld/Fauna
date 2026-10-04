"""Tests for bird sound ID (/api/identify-audio, /identify-audio page).

The BirdNET analyzer is mocked (no model, no network). A live check runs
only with FAUNA_LIVE_TESTS=1 *and* birdnet-analyzer installed with its model.
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

from app import birdnet  # noqa: E402
from app.database import UPLOAD_DIR, init_db  # noqa: E402
from app.main import app  # noqa: E402

assert UPLOAD_DIR

init_db()
client = TestClient(app)

CANNED = [
    {
        "taxon_id": None,
        "common_name": "Black-capped Chickadee",
        "scientific_name": "Poecile atricapillus",
        "rank": "species",
        "vision_score": None,
        "combined_score": 0.8141,
        "photo_url": "https://example.com/chickadee.jpg",
    },
    {
        "taxon_id": None,
        "common_name": "House Finch",
        "scientific_name": "Haemorhous mexicanus",
        "rank": "species",
        "vision_score": None,
        "combined_score": 0.6394,
        "photo_url": None,
    },
]

FAKE_WAV = b"RIFF" + b"\x00" * 128


def _upload():
    return client.post(
        "/api/identify-audio", files={"file": ("clip.wav", FAKE_WAV, "audio/wav")}
    )


def test_identify_audio_returns_suggestions(monkeypatch):
    import app.main as main_mod

    monkeypatch.setattr(main_mod.birdnet, "analyze_clip", lambda *a, **k: CANNED)
    r = _upload()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["error"] is None
    assert body["suggestions"] == CANNED


def test_identify_audio_not_installed(monkeypatch):
    import app.main as main_mod

    monkeypatch.setattr(main_mod.birdnet, "is_available", lambda: False)
    r = _upload()
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["suggestions"] == []
    assert body["error"] == "not_installed"


def test_identify_audio_analysis_failed(monkeypatch):
    import app.main as main_mod

    def _boom(*a, **k):
        raise RuntimeError("model exploded")

    monkeypatch.setattr(main_mod.birdnet, "analyze_clip", _boom)
    r = _upload()
    assert r.status_code == 200, r.text
    assert r.json()["error"] == "analysis_failed"


def test_identify_audio_rejects_bad_type():
    r = client.post(
        "/api/identify-audio", files={"file": ("notes.txt", b"hello", "text/plain")}
    )
    assert r.status_code == 400


def test_identify_audio_page_renders():
    r = client.get("/identify-audio")
    assert r.status_code == 200
    html = r.text
    assert "What did I hear?" in html
    assert "/api/identify-audio" in html
    assert "Start recording" in html


def test_nav_links_sound_id():
    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/identify-audio"' in r.text
    assert "What did I hear?" in r.text


def test_analyze_clip_filters_non_bird_and_ranks(monkeypatch):
    """End-to-end through analyze_clip with a fake analyzer: Engine (0.95)
    must not be suggested; the chickadee's best chunk (0.81) wins."""
    import sys
    import types

    fake_mod = types.ModuleType("birdnet_analyzer")
    fake_analyze_mod = types.ModuleType("birdnet_analyzer.analyze")

    def fake_analyze(audio_input, output=None, **kwargs):
        import csv

        name = Path(audio_input).stem
        with open(
            os.path.join(output, f"{name}.BirdNET.results.csv"), "w", newline=""
        ) as f:
            w = csv.writer(f)
            w.writerow(["Start (s)", "End (s)", "Scientific name",
                        "Common name", "Confidence", "File"])
            w.writerow(["0.0", "3.0", "Engine", "Engine", "0.95", "clip.wav"])
            w.writerow(["3.0", "6.0", "Poecile atricapillus",
                        "Black-capped Chickadee", "0.81", "clip.wav"])
            w.writerow(["6.0", "9.0", "Poecile atricapillus",
                        "Black-capped Chickadee", "0.40", "clip.wav"])

    fake_analyze_mod.analyze = fake_analyze
    fake_mod.analyze = fake_analyze_mod
    monkeypatch.setitem(sys.modules, "birdnet_analyzer", fake_mod)
    monkeypatch.setitem(sys.modules, "birdnet_analyzer.analyze", fake_analyze_mod)
    monkeypatch.setattr(birdnet, "is_available", lambda: True)

    suggestions = birdnet.analyze_clip(b"fake-audio", "clip.wav", enrich=False)
    assert len(suggestions) == 1
    top = suggestions[0]
    assert top["scientific_name"] == "Poecile atricapillus"
    assert top["common_name"] == "Black-capped Chickadee"
    assert top["combined_score"] == 0.81
    assert top["rank"] == "species"


LIVE = pytest.mark.skipif(
    os.environ.get("FAUNA_LIVE_TESTS") != "1" or not birdnet.is_available(),
    reason="live test; needs FAUNA_LIVE_TESTS=1 and birdnet-analyzer installed",
)


@LIVE
def test_identify_audio_live():
    import urllib.request

    url = ("https://raw.githubusercontent.com/birdnet-team/birdnet-test-data"
           "/main/soundscape/soundscape.wav")
    with urllib.request.urlopen(url, timeout=120) as resp:
        data = resp.read()
    assert len(data) > 1_000_000
    suggestions = birdnet.analyze_clip(data, "soundscape.wav", enrich=False)
    assert suggestions, "expected at least one suggestion"
    top = suggestions[0]
    assert top["scientific_name"]
    assert top["combined_score"] > 0
    print("top live suggestion:", top["common_name"], top["scientific_name"],
          round(top["combined_score"], 2))
