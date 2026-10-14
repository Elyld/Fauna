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


def test_species_route_resolves_common_name_for_eol(monkeypatch):
    """Route looks EOL up by the iNat-resolved scientific name, so common
    names like 'cottontail' (which EOL can't match) still get a write-up."""
    from fastapi.testclient import TestClient

    import app.main as main_mod

    seen = {}

    def fake_taxon_info(name):
        assert name == "cottontail"
        return {"common_name": "Cottontail Rabbits",
                "scientific_name": "Sylvilagus"}

    def fake_eol_info(session, sci_name, api_key=None):
        seen["name"] = sci_name
        return {"summary": "A rabbit genus.",
                "eol_url": "https://eol.org/pages/10818"}

    monkeypatch.setattr(main_mod, "_taxon_info", fake_taxon_info)
    monkeypatch.setattr(main_mod.eol, "get_species_info", fake_eol_info)
    client = TestClient(main_mod.app)
    r = client.get("/species/cottontail")
    assert r.status_code == 200
    assert seen["name"] == "Sylvilagus"
    assert "About this species" in r.text
    assert "A rabbit genus." in r.text


def _page_json(lang_texts):
    objs = []
    for lang, desc, subject in lang_texts:
        objs.append({
            "dataType": "http://purl.org/dc/dcmitype/Text",
            "language": lang,
            "description": f"<p>{desc}</p>",
            "subject": [subject],
            "source": "http://en.wikipedia.org/wiki/X",
        })
    return {"taxonConcept": {"dataObjects": objs}}


def test_fetch_description_english_only(monkeypatch):
    fake = _fake_get_factory([
        ("https://eol.org/api/pages/1.0/5.json", _page_json([
            ("zh", "灰松鼠是一种松鼠", "Description"),
            ("en", "The eastern gray squirrel is a tree squirrel native to eastern North America, known for its bushy tail and adaptability to urban environments.", "Description"),
        ])),
    ])
    monkeypatch.setattr(eol.httpx, "get", fake)
    d = eol.fetch_description(5)
    assert d is not None
    assert "eastern gray squirrel" in d["text"]
    assert "<p>" not in d["text"]
    assert d["source"] == "Wikipedia"


def test_fetch_description_none_when_no_english(monkeypatch):
    fake = _fake_get_factory([
        ("https://eol.org/api/pages/1.0/6.json", _page_json([
            ("de", "Das Grauhörnchen ist ein Nagetier.", "Description"),
        ])),
    ])
    monkeypatch.setattr(eol.httpx, "get", fake)
    assert eol.fetch_description(6) is None


def test_format_trait_value():
    assert eol._format_trait_value({"measurement": "253.48", "units": "mm"}) == "253.5 mm"
    assert eol._format_trait_value({"normal_measurement": "24", "normal_units": "g"}) == "24 g"
    assert eol._format_trait_value({"object": "omnivore"}) == "omnivore"
    assert eol._format_trait_value({"literal": "solitary"}) == "solitary"
    assert eol._format_trait_value({}) is None


def test_curate_cards_picks_interesting_traits():
    rows = [
        {"predicate": "body mass", "measurement": "500", "units": "g"},
        {"predicate": "trophic guild", "object": "omnivore"},
        {"predicate": "maximum longevity", "measurement": "23.6", "units": "years"},
        {"predicate": "some obscure metric", "measurement": "1", "units": "x"},
    ]
    cards = eol._curate_cards(rows)
    labels = [c["label"] for c in cards]
    assert labels == ["Weight", "Diet", "Lifespan"]
    assert cards[0]["value"] == "500 g"
    assert cards[0]["icon"] == "⚖️"


def test_fetch_traits_needs_key(monkeypatch):
    assert eol.fetch_traits(1, "") is None
    assert eol.fetch_traits(1, "   ") is None


def test_fetch_traits_parses_csv(monkeypatch):
    csv_text = (
        "predicate,measurement,units,normal_measurement,normal_units,object,literal\n"
        "body mass,500,g,0.5,kg,,\n"
        "trophic guild,,,,,omnivore,\n"
    )
    fake = _fake_get_factory([(eol.CYPHER_URL, {"__csv__": csv_text})])

    class _CsvResp:
        text = csv_text

        def raise_for_status(self):
            pass

    def fake_get(url, params=None, headers=None, timeout=None):
        assert url == eol.CYPHER_URL
        assert headers["Authorization"] == "JWT sekrit"
        assert "page_id: 42" in params["query"]
        assert "LIMIT" in params["query"]
        return _CsvResp()

    monkeypatch.setattr(eol.httpx, "get", fake_get)
    cards = eol.fetch_traits(42, "sekrit")
    assert [c["label"] for c in cards] == ["Weight", "Diet"]
    assert cards[0]["value"] == "0.5 kg"  # normal_measurement preferred


def test_species_info_refetches_when_key_added(monkeypatch):
    calls = {"n": 0}

    def fake_get(url, params=None, headers=None, timeout=None):
        calls["n"] += 1
        if "search" in url:
            return _FakeResp({"results": [{"id": 7, "title": "Vulpes vulpes"}]})
        if "brief_summary" in url:
            return _FakeResp({"brief_summary": "A fox."})
        if "pages/1.0" in url:
            return _FakeResp({"taxonConcept": {"dataObjects": []}})
        if "service/cypher" in url:
            class _CsvResp:
                text = "predicate,measurement,units,normal_measurement,normal_units,object,literal\n"
                def raise_for_status(self): pass
            return _CsvResp()
        raise AssertionError(url)

    monkeypatch.setattr(eol.httpx, "get", fake_get)
    session = SessionLocal()
    try:
        no_key = eol.get_species_info(session, "Vulpes vulpes")
        # Local trait pack is the primary card source: cards work with no key.
        assert isinstance(no_key["traits"], list) and no_key["traits"]
        assert {c["label"] for c in no_key["traits"]} >= {"Weight", "Diet"}
        n1 = calls["n"]
        # cached: no refetch without key change
        eol.get_species_info(session, "Vulpes vulpes")
        assert calls["n"] == n1
        # key added -> refetch (EOL stays the fallback for uncovered species)
        with_key = eol.get_species_info(session, "Vulpes vulpes", api_key="k1")
        assert calls["n"] > n1
        assert with_key["traits"] == no_key["traits"]
    finally:
        session.close()


def test_settings_accepts_eol_key():
    from fastapi.testclient import TestClient

    import app.main as main_mod

    client = TestClient(main_mod.app)
    r = client.put("/api/settings", json={"eol_api_key": "sekrit"})
    assert r.status_code == 200
    r = client.get("/api/settings")
    assert r.json()["eol_api_key_configured"] is True
    # write-only: value never leaks
    assert "sekrit" not in r.text
    r = client.put("/api/settings", json={"eol_api_key": ""})
    assert r.status_code == 200
    assert client.get("/api/settings").json()["eol_api_key_configured"] is False


def test_eol_section_renders_cards_and_description():
    html = pages._eol_section({
        "summary": "A fox.",
        "eol_url": "https://eol.org/pages/7",
        "traits": [{"icon": "🍽️", "label": "Diet", "value": "omnivore"}],
        "description": {"text": "Longer article here.",
                        "source": "Wikipedia",
                        "source_url": "http://en.wikipedia.org/wiki/X"},
    })
    assert "Did you know" in html
    assert "omnivore" in html
    assert "fact-cards" in html
    assert "Read more about this species" in html
    assert "Longer article here." in html
    # without traits/description: plain summary only
    html2 = pages._eol_section({"summary": "A fox.",
                                 "eol_url": "https://eol.org/pages/7",
                                 "traits": None, "description": None})
    assert "Did you know" not in html2
    assert "Read more" not in html2


def test_eol_section_credits_local_trait_pack():
    base = {
        "summary": "A fox.",
        "eol_url": "https://eol.org/pages/7",
        "traits": [{"icon": "🍽️", "label": "Diet", "value": "omnivore"}],
    }
    local = pages._eol_section({**base, "traits_source": "local"})
    assert "EltonTraits" in local and "AnAge" in local
    assert "AVONET" in local and "PanTHERIA" in local
    # EOL-sourced cards keep the section's existing EOL credit only
    eol = pages._eol_section({**base, "traits_source": "eol"})
    assert "EltonTraits" not in eol
    # cached payloads written before traits_source existed render fine
    legacy = pages._eol_section(base)
    assert "Did you know" in legacy
    assert "EltonTraits" not in legacy


def test_clean_description_strips_boilerplate():
    raw = "<p>More info for the term: fruit Red foxes are omnivorous.</p>"
    assert eol._clean_description(raw) == "Red foxes are omnivorous."
    raw2 = "More info on this topic. This species can be found here."
    assert eol._clean_description(raw2) == "This species can be found here."


def test_fetch_description_prefers_overview(monkeypatch):
    fake = _fake_get_factory([
        ("https://eol.org/api/pages/1.0/9.json", _page_json([
            ("en", "More info for the term: x " + "Habitat words. " * 40, "Habitat"),
            ("en", "Foxes are clever mammals that adapt remarkably well to many different environments all around the world.", "Brief Summary"),
        ])),
    ])
    monkeypatch.setattr(eol.httpx, "get", fake)
    d = eol.fetch_description(9)
    assert d is not None
    assert d["text"].startswith("Foxes are clever")


def test_species_info_refetches_on_version_change(monkeypatch):
    """Stale cache from an older app version must not hide new card sources.

    Regression test: v0.3.0 cached traits=None (no local pack yet); after
    upgrading to v0.4.0 the cached payload must be ignored so the local
    trait pack gets a chance.
    """
    def fake_get(url, params=None, headers=None, timeout=None):
        if "search" in url:
            return _FakeResp({"results": [{"id": 7, "title": "Vulpes vulpes"}]})
        if "brief_summary" in url:
            return _FakeResp({"brief_summary": "A fox."})
        if "pages/1.0" in url:
            return _FakeResp({"taxonConcept": {"dataObjects": []}})
        raise AssertionError(url)

    monkeypatch.setattr(eol.httpx, "get", fake_get)
    session = SessionLocal()
    try:
        # Simulate a v0.3.0-era cached payload (no version field, no traits).
        eol._write_cache(session, eol._key("Vulpes vulpes"), {
            "summary": "A fox.",
            "eol_url": "https://eol.org/pages/7",
            "page_id": 7,
            "description": None,
            "traits": None,
            "traits_source": None,
            "key_hash": eol._key_hash(None),
        })
        info = eol.get_species_info(session, "Vulpes vulpes")
        # Cache must be ignored: fresh lookup runs and local cards appear.
        assert info["traits"], "stale v0.3.0 cache hid the local trait pack"
        assert info["version"] == eol.VERSION
        # Second call hits the fresh cache (no extra HTTP).
        calls = {"n": 0}
        orig = eol.httpx.get
        def counting_get(*a, **k):
            calls["n"] += 1
            return orig(*a, **k)
        monkeypatch.setattr(eol.httpx, "get", counting_get)
        info2 = eol.get_species_info(session, "Vulpes vulpes")
        assert calls["n"] == 0
        assert info2["traits"] == info["traits"]
    finally:
        session.close()
