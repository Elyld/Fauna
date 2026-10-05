"""eBird "Download My Data" CSV import.

Parses the MyEBirdData export defensively: headers are matched
case-insensitively, optional columns may be missing entirely, and real-world
exports vary slightly in date/time formatting.
"""
from __future__ import annotations

import csv
import io
import re
from datetime import datetime

# Header aliases (lowercased, stripped) -> canonical field.
_HEADER_ALIASES = {
    "submission id": "submission_id",
    "submission_id": "submission_id",
    "common name": "common_name",
    "scientific name": "scientific_name",
    "taxonomic order": "taxonomic_order",
    "count": "count",
    "state/province": "state",
    "state": "state",
    "county": "county",
    "location": "location",
    "location id": "location_id",
    "latitude": "latitude",
    "longitude": "longitude",
    "date": "date",
    "time": "time",
    "protocol": "protocol",
    "duration (min)": "duration_min",
    "observation details": "obs_details",
    "checklist comments": "checklist_comments",
    "breeding code": "breeding_code",
}

_DATE_FORMATS = ("%m-%d-%Y", "%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y")
_TIME_FORMATS = ("%I:%M %p", "%I:%M%p", "%H:%M", "%I %p")


def _parse_observed_at(date_s: str, time_s: str) -> datetime | None:
    date_s = (date_s or "").strip()
    time_s = (time_s or "").strip()
    if not date_s:
        return None
    dt = None
    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(date_s, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return None
    if time_s:
        for fmt in _TIME_FORMATS:
            try:
                t = datetime.strptime(time_s.upper().replace(".", ""), fmt)
                dt = dt.replace(hour=t.hour, minute=t.minute)
                break
            except ValueError:
                continue
    return dt


def _parse_count(raw: str) -> tuple[int | None, str | None]:
    """Return (count, note). eBird uses 'X' for present-but-not-counted."""
    raw = (raw or "").strip()
    if not raw:
        return None, None
    if raw.upper() == "X":
        return 1, "Count not recorded in eBird (X)"
    try:
        return int(float(raw)), None
    except ValueError:
        return None, f"Unparseable eBird count {raw!r} — left blank"


def _parse_float(raw: str) -> float | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _build_notes(row: dict) -> str | None:
    parts: list[str] = []
    if row.get("obs_details"):
        parts.append(row["obs_details"].strip())
    if row.get("checklist_comments"):
        parts.append(row["checklist_comments"].strip())
    county = (row.get("county") or "").strip()
    state = (row.get("state") or "").strip()
    where = ", ".join(p for p in (county, state) if p)
    if where:
        parts.append(f"eBird location: {where}")
    if row.get("_count_note"):
        parts.append(row["_count_note"])
    text = "\n\n".join(p for p in parts if p)
    return text or None


def parse_ebird_csv(text: str) -> dict:
    """Parse eBird CSV text.

    Returns {"rows": [...], "skipped": [{"line": int, "reason": str}]}.
    Each row is a dict ready for Fauna's observation fields plus
    ``external_id`` (``ebird:<submission id>``) for dedup.
    """
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return {"rows": [], "skipped": [{"line": 1, "reason": "empty file"}]}

    # Map file headers -> canonical fields (case-insensitive).
    col_map: dict[str, str] = {}
    for header in reader.fieldnames:
        key = (header or "").strip().lower()
        if key in _HEADER_ALIASES:
            col_map[_HEADER_ALIASES[key]] = header

    rows: list[dict] = []
    skipped: list[dict] = []
    for lineno, raw in enumerate(reader, start=2):
        row = {field: (raw.get(header) or "") for field, header in col_map.items()}
        common = row.get("common_name", "").strip()
        sci = row.get("scientific_name", "").strip()
        if not common and not sci:
            skipped.append({"line": lineno, "reason": "no species name"})
            continue

        count, count_note = _parse_count(row.get("count", ""))
        row["_count_note"] = count_note
        observed_at = _parse_observed_at(row.get("date", ""), row.get("time", ""))

        submission = row.get("submission_id", "").strip()
        parsed = {
            "species_name": common or None,
            "scientific_name": sci or None,
            "count": count,
            "observed_at": observed_at.isoformat() if observed_at else None,
            "latitude": _parse_float(row.get("latitude", "")),
            "longitude": _parse_float(row.get("longitude", "")),
            "location_name": row.get("location", "").strip() or None,
            "notes": _build_notes(row),
            "external_id": f"ebird:{submission}" if submission else None,
            "needs_id": False,
        }
        rows.append(parsed)

    return {"rows": rows, "skipped": skipped}


def dedup_against(existing_ids: set[str], rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split rows into (new, already_imported), also catching dupes within the file."""
    new, already = [], []
    seen: set[str] = set()
    for row in rows:
        ext = row.get("external_id")
        if ext and (ext in existing_ids or ext in seen):
            already.append(row)
        else:
            new.append(row)
            if ext:
                seen.add(ext)
    return new, already
