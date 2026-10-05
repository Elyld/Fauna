"""eBird CSV import: mapping, X-counts, dedup, preview/confirm round-trip.

Run:  cd ~/workspace/fauna && PYTHONPATH=. .venv/bin/python -m pytest -q
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fauna-test-ebird-"))
os.environ.setdefault("FAUNA_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("FAUNA_UPLOAD_DIR", str(TMP / "photos"))

from fastapi.testclient import TestClient  # noqa: E402

from app import ebird_import  # noqa: E402
from app.database import UPLOAD_DIR, init_db  # noqa: E402
from app.main import app  # noqa: E402

assert UPLOAD_DIR  # keep the conventional import used

init_db()
client = TestClient(app)

HEADER = (
    "Submission ID,Common Name,Scientific Name,Taxonomic Order,Count,"
    "State/Province,County,Location,Location ID,Latitude,Longitude,"
    "Date,Time,Protocol,Duration (Min),Observation Details,Checklist Comments"
)

FIXTURE = HEADER + "\n" + "\n".join(
    [
        "S12345678,American Robin,Turdus migratorius,1234,5,Kansas,Shawnee,Backyard,L123,39.05,-95.68,10-03-2026,07:30 AM,Stationary,30,Singing from the oak,,",
        "S12345679,Northern Cardinal,Cardinalis cardinalis,1235,X,Kansas,Shawnee,Backyard,L123,39.05,-95.68,10-03-2026,,Stationary,30,,Morning visit",
        "S12345680,,,,Kansas,Shawnee,Backyard,L123,39.05,-95.68,10-02-2026,08:00 AM,Stationary,30,,,",
    ]
)


def _preview(csv_text: str = FIXTURE):
    r = client.post(
        "/api/import/ebird/preview",
        files={"file": ("myebird.csv", csv_text, "text/csv")},
    )
    assert r.status_code == 200, r.text
    return r.json()


def _fixture(tag: str) -> str:
    """FIXTURE with unique submission IDs per test (tests share one DB)."""
    return FIXTURE.replace("S12345678", f"S{tag}1").replace(
        "S12345679", f"S{tag}2"
    ).replace("S12345680", f"S{tag}3")


def test_parse_mapping():
    parsed = ebird_import.parse_ebird_csv(FIXTURE)
    assert len(parsed["rows"]) == 2
    assert len(parsed["skipped"]) == 1
    assert parsed["skipped"][0]["reason"] == "no species name"
    robin = parsed["rows"][0]
    assert robin["species_name"] == "American Robin"
    assert robin["scientific_name"] == "Turdus migratorius"
    assert robin["count"] == 5
    assert robin["observed_at"] == "2026-10-03T07:30:00"
    assert robin["latitude"] == 39.05
    assert robin["longitude"] == -95.68
    assert robin["location_name"] == "Backyard"
    assert robin["external_id"] == "ebird:S12345678"
    assert "Singing from the oak" in (robin["notes"] or "")
    assert "Shawnee, Kansas" in (robin["notes"] or "")


def test_x_count_becomes_one_with_note():
    parsed = ebird_import.parse_ebird_csv(FIXTURE)
    cardinal = parsed["rows"][1]
    assert cardinal["count"] == 1
    assert "Count not recorded in eBird (X)" in (cardinal["notes"] or "")
    # blank time -> date at midnight
    assert cardinal["observed_at"] == "2026-10-03T00:00:00"


def test_case_insensitive_and_sparse_headers():
    csv_text = "submission id,common name,scientific name,date\nS9,Blue Jay,Cyanocitta cristata,2026-10-01\n"
    parsed = ebird_import.parse_ebird_csv(csv_text)
    assert len(parsed["rows"]) == 1
    row = parsed["rows"][0]
    assert row["species_name"] == "Blue Jay"
    assert row["observed_at"] == "2026-10-01T00:00:00"
    assert row["external_id"] == "ebird:S9"
    assert row["location_name"] is None


def test_blank_date_gives_null_observed_at():
    csv_text = "Common Name,Scientific Name\nHouse Finch,Haemorhous mexicanus\n"
    parsed = ebird_import.parse_ebird_csv(csv_text)
    assert parsed["rows"][0]["observed_at"] is None
    assert parsed["rows"][0]["external_id"] is None


def test_preview_confirm_roundtrip():
    preview = _preview(_fixture("A"))
    assert preview["total_rows"] == 2
    assert preview["new_count"] == 2
    assert preview["already_count"] == 0

    r = client.post("/api/import/ebird/confirm", json={"rows": preview["new"]})
    assert r.status_code == 200, r.text
    result = r.json()
    assert result["imported"] == 2
    assert result["skipped_dupes"] == 0

    # Sightings are really there, with external ids.
    r = client.get("/api/observations")
    assert r.status_code == 200
    obs = r.json()["observations"]
    exts = {o["external_id"] for o in obs}
    assert "ebird:SA1" in exts
    assert "ebird:SA2" in exts


def test_dedup_double_import_is_noop():
    csv_text = _fixture("B")
    first = _preview(csv_text)
    assert first["new_count"] == 2
    assert client.post("/api/import/ebird/confirm", json={"rows": first["new"]}).json()[
        "imported"
    ] == 2

    second = _preview(csv_text)
    assert second["new_count"] == 0, "re-import must find nothing new"
    assert second["already_count"] == 2

    r = client.post("/api/import/ebird/confirm", json={"rows": second["new"]})
    assert r.json()["imported"] == 0


def test_confirm_rechecks_dupes():
    csv_text = _fixture("C")
    preview = _preview(csv_text)
    rows = preview["new"]
    assert len(rows) == 2
    # Post the same rows twice — the second confirm is fully deduped server-side.
    assert (
        client.post("/api/import/ebird/confirm", json={"rows": rows}).json()["imported"]
        == 2
    )
    again = client.post("/api/import/ebird/confirm", json={"rows": rows}).json()
    assert again["imported"] == 0
    assert again["skipped_dupes"] == 2


def test_import_page_renders():
    r = client.get("/import")
    assert r.status_code == 200
    assert "eBird" in r.text
    assert "/api/import/ebird/preview" in r.text
