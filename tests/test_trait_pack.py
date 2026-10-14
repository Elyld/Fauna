"""Offline trait pack: parsers, formatting, card pipeline.

Run:  cd ~/workspace/fauna && PYTHONPATH=. .venv/bin/python -m pytest -q
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fauna-test-traits-"))
os.environ.setdefault("FAUNA_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("FAUNA_UPLOAD_DIR", str(TMP / "photos"))

from app import eol  # noqa: E402
from app import trait_pack  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402

init_db()

session = SessionLocal()
trait_pack.ensure_loaded(session)


def test_formatters():
    assert trait_pack._fmt_mass_g(85) == "85 g"
    assert trait_pack._fmt_mass_g(78.5) == "78.5 g"
    assert trait_pack._fmt_mass_g(120000) == "120 kg"
    assert trait_pack._fmt_mass_g(61900) == "61.9 kg"
    assert trait_pack._fmt_mass_g(None) is None
    assert trait_pack._fmt_mass_g(-999) is None
    assert trait_pack._fmt_years(17) == "17 years"
    assert trait_pack._fmt_years(23.6) == "23.6 years"
    assert trait_pack._fmt_years(0) is None
    assert trait_pack._fmt_years(None) is None


def test_diet_from_percentages():
    row = {"Diet-Fruit": "50", "Diet-Inv": "50", "Diet-Seed": "0"}
    assert trait_pack._diet_from_percentages(row) == "invertebrates 50%, fruit 50%"
    row = {"Diet-Inv": "100", "Diet-Fruit": "0"}
    assert trait_pack._diet_from_percentages(row) == "invertebrates"
    row = {"Diet-Inv": "0", "Diet-Fruit": ""}
    assert trait_pack._diet_from_percentages(row) is None


def test_robin_cards():
    rows = trait_pack.fetch_local_trait_rows(session, "Turdus migratorius")
    assert rows, "robin should be in the trait pack"
    cards = eol._curate_cards(rows)
    by_label = {c["label"]: c["value"] for c in cards}
    assert "Weight" in by_label
    assert "Diet" in by_label
    assert "Lifespan" in by_label
    assert "Habitat" in by_label
    assert by_label["Habitat"] == "Forest"


def test_squirrel_cards():
    rows = trait_pack.fetch_local_trait_rows(session, "Sciurus carolinensis")
    cards = eol._curate_cards(rows)
    by_label = {c["label"]: c["value"] for c in cards}
    assert by_label["Weight"] == "440 g"
    assert by_label["Gestation"] == "45 days"
    # litter size is a whole-number average, not "3.0"
    assert by_label["Young per birth"] == "3"
    assert by_label["Active"] == "diurnal"


def test_case_insensitive_lookup():
    lower = trait_pack.fetch_local_trait_rows(session, "turdus migratorius")
    upper = trait_pack.fetch_local_trait_rows(session, "TURDUS MIGRATORIUS")
    assert lower and lower == upper


def test_unknown_species_returns_empty():
    assert trait_pack.fetch_local_trait_rows(session, "Notus realus") == []
    assert trait_pack.fetch_local_trait_rows(session, "") == []


def test_ensure_loaded_idempotent():
    n1 = trait_pack.ensure_loaded(session)
    n2 = trait_pack.ensure_loaded(session)
    assert n1 == n2 and n1 > 50000


def test_ensure_loaded_never_raises(tmp_path):
    # Missing data dir -> 0 rows, no exception (graceful degradation).
    import app.trait_pack as tp

    orig = tp.TRAIT_DATA_DIR
    tp.TRAIT_DATA_DIR = tmp_path / "nope"
    try:
        assert tp.ensure_loaded(session) == trait_pack.ensure_loaded(session)
    finally:
        tp.TRAIT_DATA_DIR = orig


def test_card_icons_and_labels():
    rows = trait_pack.fetch_local_trait_rows(session, "Odocoileus virginianus")
    cards = eol._curate_cards(rows)
    assert cards, "deer should have cards"
    for c in cards:
        assert set(c) == {"icon", "label", "value"}
        assert c["icon"] and c["label"] and c["value"]
