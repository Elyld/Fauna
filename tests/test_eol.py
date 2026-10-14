"""EOL species write-ups: client parsing, caching, page rendering.

Run:  cd ~/workspace/fauna && PYTHONPATH=. .venv/bin/python -m pytest -q
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fauna-test-eol-"))
os.environ.setdefault("FAUNA_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("FAUNA_UPLOAD_DIR", str(TMP / "photos"))

from app import eol  # noqa: E402
from app import pages  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402

init_db()


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def _fake_get_factory(routes):
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append(url)
        for prefix, payload in routes:
            if url.startswith(prefix):
                return _FakeResp(payload)
        raise AssertionError(f"unexpected URL: {url}")

    fake_get.calls = calls
    return fake_get


def test_search_page_id_exact_match(monkeypatch):
    fake = _fake_get_factory([
        ("https://eol.org/api/search/1.0.json", {
            "results": [
                {"id": 111, "title": "Sciurus carolinensis extimus"},
                {"id": 347685, "title": "Sciurus carolinensis"},
            ]
        }),
    ])
    monkeypatch.setattr(eol.httpx, "get", fake)
    assert eol.search_page_id("Sciurus carolinensis") == 347685
    # no exact match -> None
    fake2 = _fake_get_factory([
        ("https://eol.org/api/search/1.0.json", {"results": [
            {"id": 999, "title": "Something else entirely"},
        ]}),
    ])
    monkeypatch.setattr(eol.httpx, "get", fake2)
    assert eol.search_page_id("Sciurus carolinensis") is None
    assert eol.search_page_id("") is None


def test_fetch_brief_summary(monkeypatch):
    fake = _fake_get_factory([
        ("https://eol.org/api/pages/347685/brief_summary.json",
         {"brief_summary": "They are solitary, diurnal omnivores."}),
    ])
    monkeypatch.setattr(eol.httpx, "get", fake)
    assert eol.fetch_brief_summary(347685) == "They are solitary, diurnal omnivores."
    fake2 = _fake_get_factory([
        ("https://eol.org/api/pages/1/brief_summary.json", {"brief_summary": "  "}),
    ])
    monkeypatch.setattr(eol.httpx, "get", fake2)
    assert eol.fetch_brief_summary(1) is None


def test_get_species_info_caches(monkeypatch):
    fake = _fake_get_factory([
        ("https://eol.org/api/search/1.0.json", {"results": [
            {"id": 347685, "title": "Sciurus carolinensis"},
        ]}),
        ("https://eol.org/api/pages/347685/brief_summary.json",
         {"brief_summary": "A squirrel."}),
    ])
    monkeypatch.setattr(eol.httpx, "get", fake)
    session = SessionLocal()
    try:
        first = eol.get_species_info(session, "Sciurus carolinensis")
        assert first["summary"] == "A squirrel."
        assert first["eol_url"] == "https://eol.org/pages/347685"
        n_calls = len(fake.calls)
        second = eol.get_species_info(session, "Sciurus carolinensis")
        assert second == first
        assert len(fake.calls) == n_calls  # cache hit: no new HTTP
    finally:
        session.close()


def test_get_species_info_never_raises(monkeypatch):
    def boom(url, params=None, timeout=None):
        raise ConnectionError("down")

    monkeypatch.setattr(eol.httpx, "get", boom)
    session = SessionLocal()
    try:
        # fresh name (not cached by earlier tests) -> network fails -> None
        assert eol.get_species_info(session, "Tamiasciurus hudsonicus") is None
        assert eol.get_species_info(session, "") is None
    finally:
        session.close()


def test_eol_section_renders():
    html = pages._eol_section({
        "summary": "They are solitary.",
        "eol_url": "https://eol.org/pages/347685",
        "page_id": 347685,
    })
    assert "About this species" in html
    assert "They are solitary." in html
    assert "Encyclopedia of Life" in html
    assert "https://eol.org/pages/347685" in html
    assert pages._eol_section(None) == ""
    assert pages._eol_section({}) == ""
    # summary text is escaped
    html2 = pages._eol_section({"summary": "<script>alert(1)</script>",
                                "eol_url": "https://eol.org/"})
    assert "<script>" not in html2


def test_species_page_includes_eol():
    html = pages.species_page(
        taxon={"common_name": "Eastern Gray Squirrel",
               "scientific_name": "Sciurus carolinensis"},
        range_data={}, own_points=[], sightings=[],
        display_name="Sciurus carolinensis",
        eol_info={"summary": "A squirrel.", "eol_url": "https://eol.org/pages/1"},
    )
    assert "About this species" in html
    html2 = pages.species_page(
        taxon=None, range_data={}, own_points=[], sightings=[],
        display_name="Mystery bird", eol_info=None,
    )
    assert "About this species" not in html2
