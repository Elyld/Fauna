"""Fauna — wildlife observation journal (working name; will change)."""
from __future__ import annotations

import csv
import io
import json
import logging
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app import birdnet
from app import ebird_import
from app import inat
from app import nearby as nearby_mod
from app import pages
from app import range_map
from app import vision_id
from app.database import DATABASE_URL, UPLOAD_DIR, SessionLocal, get_session, init_db
from app.models import Observation, ObservationPhoto, Setting, Wishlist
from app.version import APP_NAME, VERSION

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=APP_NAME, version=VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:4001", "http://127.0.0.1:4001"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/photos", StaticFiles(directory=str(UPLOAD_DIR)), name="photos")
STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/manifest.json")
def pwa_manifest():
    """PWA manifest (served at root; the file lives under /static)."""
    return FileResponse(
        str(STATIC_DIR / "manifest.json"),
        media_type="application/manifest+json",
    )

ALLOWED_PHOTO_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}


class ObservationIn(BaseModel):
    species_name: str | None = None
    scientific_name: str | None = None
    count: int | None = None
    observed_at: datetime | None = None
    latitude: float | None = None
    longitude: float | None = None
    location_name: str | None = None
    notes: str | None = None
    photo_path: str | None = None  # may reference a pending_ upload from /api/identify
    needs_id: bool | None = None  # "I'm not sure what this is"


def _obs_to_dict(o: Observation) -> dict:
    photos = [
        {"id": p.id, "photo_path": p.photo_path, "photo_url": f"/photos/{p.photo_path}"}
        for p in (o.photos or [])
    ]
    return {
        "id": o.id,
        "species_name": o.species_name,
        "scientific_name": o.scientific_name,
        "count": o.count,
        "observed_at": o.observed_at.isoformat() if o.observed_at else None,
        "latitude": o.latitude,
        "longitude": o.longitude,
        "location_name": o.location_name,
        "notes": o.notes,
        "photo_path": o.photo_path,
        "photo_url": f"/photos/{o.photo_path}" if o.photo_path else None,
        "photos": photos,
        "needs_id": bool(o.needs_id) if o.needs_id is not None else False,
        "external_id": o.external_id,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


@app.get("/", response_class=HTMLResponse)
def index(session: Session = Depends(get_session)):
    obs = session.query(Observation).order_by(Observation.id.desc()).all()
    dicts = [_obs_to_dict(o) for o in obs]
    species = {o["species_name"] for o in dicts if o.get("species_name")}
    return pages.home_page(len(dicts), len(species), dicts[:4])


@app.get("/observations", response_class=HTMLResponse)
def observations_page(
    q: str | None = Query(None),
    needs_id: bool = Query(False),
    session: Session = Depends(get_session),
):
    query = session.query(Observation).order_by(Observation.id.desc())
    query = _apply_observation_search(query, q, needs_id)
    return pages.observations_page(
        [_obs_to_dict(o) for o in query.all()],
        q=q or "",
        needs_id_only=needs_id,
    )


def _apply_observation_search(query, q: str | None, needs_id: bool):
    """Shared text-search + needs-ID filter for the observations list."""
    if needs_id:
        query = query.filter(Observation.needs_id.is_(True))
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Observation.species_name.ilike(like),
                Observation.scientific_name.ilike(like),
                Observation.location_name.ilike(like),
                Observation.notes.ilike(like),
            )
        )
    return query


@app.get("/observations/{obs_id}/edit", response_class=HTMLResponse)
def edit_observation_page(obs_id: int, session: Session = Depends(get_session)):
    obs = session.get(Observation, obs_id)
    if obs is None:
        raise HTTPException(404, "observation not found")
    return pages.edit_observation_page(_obs_to_dict(obs))


@app.get("/observations/new", response_class=HTMLResponse)
def new_observation_page(
    species_name: str | None = Query(None),
    scientific_name: str | None = Query(None),
    photo: str | None = Query(None),  # pending_ reference from /api/identify
    needs_id: bool = Query(False),
    notes: str | None = Query(None),
):
    # Only a bare pending_ filename may be referenced (no path traversal).
    pending_photo = None
    if photo:
        name = Path(photo).name
        if name == photo and name.startswith("pending_") and (UPLOAD_DIR / name).exists():
            pending_photo = {"path": name, "url": f"/photos/{name}"}
    return pages.new_observation_page(
        {
            "species_name": species_name or "",
            "scientific_name": scientific_name or "",
            "pending_photo": pending_photo,
            "needs_id": needs_id,
            "notes": notes or "",
        }
    )


@app.get("/api/health")
def health():
    return {"ok": True, "app": APP_NAME, "version": VERSION}


# ---------------------------------------------------------------------------
# Settings (key/value store; secrets are never echoed back to the client)
# ---------------------------------------------------------------------------

PUBLIC_SETTINGS = {"vision_model", "home_latitude", "home_longitude", "home_name"}
SECRET_SETTINGS = {"openrouter_api_key"}


def get_setting(session: Session, key: str, default: str | None = None) -> str | None:
    row = session.get(Setting, key)
    if row is None or row.value is None:
        return default
    return row.value


def set_setting(session: Session, key: str, value: str | None) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value
    session.commit()


@app.get("/api/settings")
def get_settings(session: Session = Depends(get_session)):
    out: dict[str, str | bool | None] = {}
    for key in sorted(PUBLIC_SETTINGS):
        out[key] = get_setting(session, key)
    for key in sorted(SECRET_SETTINGS):
        out[f"{key}_configured"] = bool(get_setting(session, key))
    return out


class SettingsIn(BaseModel):
    openrouter_api_key: str | None = None  # empty string clears the stored key
    vision_model: str | None = None
    home_latitude: str | None = None  # strings from the form; validated below
    home_longitude: str | None = None
    home_name: str | None = None


def _parse_home_coord(value: str | None, *, lat: bool) -> str | None:
    """Validate a home coordinate string; returns the canonical string or None
    (blank clears it). Raises HTTPException(400) on junk."""
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        num = float(text)
    except ValueError:
        raise HTTPException(400, "home location must be numbers")
    lo, hi = (-90.0, 90.0) if lat else (-180.0, 180.0)
    if not (lo <= num <= hi):
        raise HTTPException(400, "home location is out of range")
    return str(num)


@app.put("/api/settings")
def put_settings(payload: SettingsIn, session: Session = Depends(get_session)):
    if payload.openrouter_api_key is not None:
        set_setting(session, "openrouter_api_key", payload.openrouter_api_key.strip() or None)
    if payload.vision_model is not None:
        set_setting(
            session,
            "vision_model",
            payload.vision_model.strip() or vision_id.DEFAULT_VISION_MODEL,
        )
    if payload.home_latitude is not None:
        set_setting(session, "home_latitude", _parse_home_coord(payload.home_latitude, lat=True))
    if payload.home_longitude is not None:
        set_setting(session, "home_longitude", _parse_home_coord(payload.home_longitude, lat=False))
    if payload.home_name is not None:
        set_setting(session, "home_name", payload.home_name.strip() or None)
    return get_settings(session)


def get_home_location(session: Session) -> dict:
    """Home location from settings: {latitude, longitude, name} or Nones."""
    lat = lon = None
    try:
        lat_raw = get_setting(session, "home_latitude")
        lon_raw = get_setting(session, "home_longitude")
        lat = float(lat_raw) if lat_raw else None
        lon = float(lon_raw) if lon_raw else None
    except (TypeError, ValueError):
        lat = lon = None
    return {
        "latitude": lat,
        "longitude": lon,
        "name": get_setting(session, "home_name"),
    }


@app.get("/settings", response_class=HTMLResponse)
def settings_page(session: Session = Depends(get_session)):
    home = get_home_location(session)
    return pages.settings_page(
        {
            "openrouter_api_key_configured": bool(get_setting(session, "openrouter_api_key")),
            "vision_model": get_setting(session, "vision_model")
            or vision_id.DEFAULT_VISION_MODEL,
            "default_vision_model": vision_id.DEFAULT_VISION_MODEL,
            "home_latitude": get_setting(session, "home_latitude") or "",
            "home_longitude": get_setting(session, "home_longitude") or "",
            "home_name": get_setting(session, "home_name") or "",
        }
    )


@app.get("/api/observations")
def list_observations(
    q: str | None = Query(None),
    needs_id: bool = Query(False),
    session: Session = Depends(get_session),
):
    query = session.query(Observation).order_by(Observation.id.desc())
    query = _apply_observation_search(query, q, needs_id)
    return {"observations": [_obs_to_dict(o) for o in query.all()]}


@app.get("/api/observations/export.csv")
def export_observations_csv(session: Session = Depends(get_session)):
    """CSV export of every sighting (Verdant-style)."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "species_name",
            "scientific_name",
            "count",
            "observed_at",
            "latitude",
            "longitude",
            "location_name",
            "notes",
            "photo_path",
            "needs_id",
            "created_at",
        ]
    )
    for o in session.query(Observation).order_by(Observation.id.asc()).all():
        d = _obs_to_dict(o)
        writer.writerow(
            [
                d["id"],
                d["species_name"],
                d["scientific_name"],
                d["count"],
                d["observed_at"],
                d["latitude"],
                d["longitude"],
                d["location_name"],
                d["notes"],
                d["photo_path"],
                d["needs_id"],
                d["created_at"],
            ]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=fauna-observations.csv"},
    )


BACKUP_PHOTO_WARN_BYTES = 500 * 1024 * 1024


def _sqlite_db_path() -> Path:
    """Filesystem path of the live SQLite database."""
    if not DATABASE_URL.startswith("sqlite:///"):
        raise HTTPException(500, "Backups require the SQLite database")
    return Path(DATABASE_URL[len("sqlite:///") :])


def _build_backup_readme(stamp: str) -> str:
    return (
        f"Fauna backup — created {stamp}\n"
        "\n"
        "What's inside this zip:\n"
        "  fauna.db          The full Fauna database (every sighting, setting,\n"
        "                  and life-list entry). Open it with any SQLite\n"
        "                  browser if you ever need to.\n"
        "  photos/           Every sighting photo, as uploaded.\n"
        "  observations.json Every sighting in plain, human-readable JSON —\n"
        "                  readable even if fauna.db won't open.\n"
        "  settings.json     Your saved settings (photo-ID model etc.). API\n"
        "                  keys are NOT included — you'll need to paste them\n"
        "                  again after a restore.\n"
        "\n"
        "How to restore:\n"
        "  1. Stop the Fauna app (stop the Docker container).\n"
        "  2. Replace fauna.db with the one from this zip, and replace the\n"
        "     contents of the photos folder with the photos/ folder from\n"
        "     this zip. (Keep a copy of the current files first, just in\n"
        "     case.)\n"
        "  3. Start the app again. Everything is back.\n"
        "\n"
        "Keep this zip somewhere safe — it's everything.\n"
    )


@app.get("/api/backup")
def download_backup():
    """Full backup download: database snapshot + all photos + JSON dumps."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    zip_name = f"fauna-backup-{stamp}.zip"
    tmp = Path(tempfile.mkdtemp(prefix="fauna-backup-"))

    def cleanup() -> None:
        shutil.rmtree(tmp, ignore_errors=True)

    try:
        # 1. Consistent live snapshot of the database. VACUUM INTO copies a
        #    live SQLite database (WAL included) into one clean file — a raw
        #    file copy could miss the -wal journal.
        snapshot = tmp / "fauna.db"
        db_path = _sqlite_db_path()
        raw = sqlite3.connect(str(db_path))
        try:
            raw.isolation_level = None  # autocommit; VACUUM needs no open txn
            quoted = str(snapshot).replace("'", "''")
            raw.execute(f"VACUUM INTO '{quoted}'")
        finally:
            raw.close()

        # 2. Photos. Big libraries are allowed through — just warn server-side.
        photo_files = sorted(p for p in UPLOAD_DIR.iterdir() if p.is_file())
        photo_bytes = sum(p.stat().st_size for p in photo_files)
        if photo_bytes > BACKUP_PHOTO_WARN_BYTES:
            logger.warning(
                "Backup photo payload is %.1f MB (over the 500MB note threshold); "
                "generating anyway",
                photo_bytes / (1024 * 1024),
            )

        # 3. Human-readable dumps: every sighting + settings (no secret values).
        with SessionLocal() as session:
            observations = [
                _obs_to_dict(o)
                for o in session.query(Observation).order_by(Observation.id.asc()).all()
            ]
            settings: dict[str, str | bool | None] = {}
            for key in sorted(PUBLIC_SETTINGS):
                settings[key] = get_setting(session, key)
            for key in sorted(SECRET_SETTINGS):
                settings[key] = (
                    "<configured>" if get_setting(session, key) else None
                )
        (tmp / "observations.json").write_text(
            json.dumps(
                {
                    "app": APP_NAME,
                    "exported_at": datetime.now().isoformat(timespec="seconds"),
                    "observations": observations,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        (tmp / "settings.json").write_text(
            json.dumps(settings, indent=2), encoding="utf-8"
        )
        (tmp / "README.txt").write_text(_build_backup_readme(stamp), encoding="utf-8")

        zip_path = tmp / zip_name
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmp / "fauna.db", "fauna.db")
            zf.write(tmp / "observations.json", "observations.json")
            zf.write(tmp / "settings.json", "settings.json")
            zf.write(tmp / "README.txt", "README.txt")
            for photo in photo_files:
                zf.write(photo, f"photos/{photo.name}")
    except Exception:
        cleanup()
        raise

    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=zip_name,
        background=BackgroundTask(cleanup),
    )


MAX_IMPORT_BYTES = 10 * 1024 * 1024  # same cap as other uploads


def _existing_external_ids(session: Session) -> set[str]:
    rows = (
        session.query(Observation.external_id)
        .filter(Observation.external_id.isnot(None))
        .all()
    )
    return {r[0] for r in rows}


@app.post("/api/import/ebird/preview")
async def ebird_import_preview(
    file: UploadFile = File(...), session: Session = Depends(get_session)
):
    """Parse an eBird 'Download My Data' CSV and report what would import.

    Two-step flow: the client shows this summary, then POSTs the returned
    ``new`` rows back to /api/import/ebird/confirm. Stateless on the server.
    """
    data = await file.read()
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(413, "file too large (10MB max)")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "could not read file as text/CSV")
    parsed = ebird_import.parse_ebird_csv(text)
    new, already = ebird_import.dedup_against(
        _existing_external_ids(session), parsed["rows"]
    )
    return {
        "total_rows": len(parsed["rows"]),
        "new_count": len(new),
        "already_count": len(already),
        "skipped": parsed["skipped"],
        "new": new,  # post these back to /confirm
    }


class EboidImportConfirm(BaseModel):
    rows: list[dict]


@app.post("/api/import/ebird/confirm")
def ebird_import_confirm(
    payload: EboidImportConfirm, session: Session = Depends(get_session)
):
    """Insert previewed rows. Re-checks dedup so re-imports are a safe no-op."""
    existing = _existing_external_ids(session)
    imported = 0
    skipped_dupes = 0
    skipped_invalid = 0
    for row in payload.rows:
        if not isinstance(row, dict) or not (
            row.get("species_name") or row.get("scientific_name")
        ):
            skipped_invalid += 1
            continue
        ext = row.get("external_id")
        if ext and ext in existing:
            skipped_dupes += 1
            continue
        observed_at = None
        if row.get("observed_at"):
            try:
                observed_at = datetime.fromisoformat(row["observed_at"])
            except ValueError:
                observed_at = None
        obs = Observation(
            species_name=row.get("species_name"),
            scientific_name=row.get("scientific_name"),
            count=row.get("count"),
            observed_at=observed_at,
            latitude=row.get("latitude"),
            longitude=row.get("longitude"),
            location_name=row.get("location_name"),
            notes=row.get("notes"),
            needs_id=False,
            external_id=ext,
        )
        session.add(obs)
        if ext:
            existing.add(ext)
        imported += 1
    session.commit()
    return {
        "imported": imported,
        "skipped_dupes": skipped_dupes,
        "skipped_invalid": skipped_invalid,
    }


@app.get("/import", response_class=HTMLResponse)
def import_page_route():
    return pages.import_page()


@app.put("/api/observations/{obs_id}")
def update_observation(
    obs_id: int, payload: ObservationIn, session: Session = Depends(get_session)
):
    """Edit a sighting's fields. Photos are replaced via POST /photo."""
    obs = session.get(Observation, obs_id)
    if obs is None:
        raise HTTPException(404, "observation not found")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key == "photo_path":
            continue  # photo swaps go through the /photo endpoint
        setattr(obs, key, value)
    session.commit()
    session.refresh(obs)
    return _obs_to_dict(obs)


@app.get("/api/observations/{obs_id}")
def get_observation(obs_id: int, session: Session = Depends(get_session)):
    obs = session.get(Observation, obs_id)
    if obs is None:
        raise HTTPException(404, "observation not found")
    return _obs_to_dict(obs)


@app.post("/api/observations")
def create_observation(payload: ObservationIn, session: Session = Depends(get_session)):
    data = payload.model_dump()
    photo_path = data.get("photo_path")
    if photo_path:
        # Claim a pending_ upload from /api/identify: it must be a bare
        # filename inside the upload dir (no path traversal), and it gets
        # renamed to a permanent name on claim.
        name = Path(photo_path).name
        if name != photo_path or not name.startswith("pending_"):
            raise HTTPException(400, "invalid photo reference")
        src = UPLOAD_DIR / name
        if src.exists():
            final = f"{uuid.uuid4().hex}{Path(name).suffix}"
            src.rename(UPLOAD_DIR / final)
            data["photo_path"] = final
        else:
            data["photo_path"] = None  # pending file vanished; save without photo
    obs = Observation(**data)
    session.add(obs)
    session.commit()
    session.refresh(obs)
    if obs.photo_path:
        # Track the claimed pending photo in the multi-photo table too.
        session.add(ObservationPhoto(observation_id=obs.id, photo_path=obs.photo_path))
        session.commit()
        session.refresh(obs)
    return _obs_to_dict(obs)


@app.delete("/api/observations/{obs_id}")
def delete_observation(obs_id: int, session: Session = Depends(get_session)):
    obs = session.get(Observation, obs_id)
    if obs is None:
        raise HTTPException(404, "observation not found")
    photo_names = [p.photo_path for p in (obs.photos or [])]
    if obs.photo_path and obs.photo_path not in photo_names:
        photo_names.append(obs.photo_path)
    session.delete(obs)
    session.commit()
    for name in photo_names:
        # don't orphan image files on disk
        (UPLOAD_DIR / Path(name).name).unlink(missing_ok=True)
    return {"deleted": obs_id}


def _store_upload(file: UploadFile) -> str:
    """Validate + save one uploaded photo; returns its stored filename."""
    ext = Path(file.filename or "").suffix.lower()[:10]
    if ext not in ALLOWED_PHOTO_EXTS:
        raise HTTPException(400, "unsupported image type")
    name = f"{uuid.uuid4().hex}{ext}"
    with (UPLOAD_DIR / name).open("wb") as f:
        shutil.copyfileobj(file.file, f)
    return name


def _add_photo_row(session: Session, obs: Observation, name: str) -> ObservationPhoto:
    """Attach a stored photo; first photo also becomes the cover."""
    row = ObservationPhoto(observation_id=obs.id, photo_path=name)
    session.add(row)
    session.flush()
    if not obs.photo_path:
        obs.photo_path = name
    return row


def _remove_photo_row(session: Session, obs: Observation, row: ObservationPhoto) -> None:
    """Delete one photo: file + row; promote the next photo if it was the cover."""
    (UPLOAD_DIR / Path(row.photo_path).name).unlink(missing_ok=True)
    was_cover = obs.photo_path == row.photo_path
    session.delete(row)
    session.flush()
    if was_cover:
        nxt = (
            session.query(ObservationPhoto)
            .filter(ObservationPhoto.observation_id == obs.id)
            .order_by(ObservationPhoto.id.asc())
            .first()
        )
        obs.photo_path = nxt.photo_path if nxt else None


@app.post("/api/observations/{obs_id}/photo")
def upload_photo(
    obs_id: int, file: UploadFile = File(...), session: Session = Depends(get_session)
):
    """Single-photo upload: the new photo becomes the cover (classic behavior).

    The previous cover photo is removed; the new one is also tracked in the
    multi-photo table so the gallery/lightbox sees it.
    """
    obs = session.get(Observation, obs_id)
    if obs is None:
        raise HTTPException(404, "observation not found")
    name = _store_upload(file)
    old_cover = obs.photo_path
    obs.photo_path = name
    row = ObservationPhoto(observation_id=obs.id, photo_path=name)
    session.add(row)
    session.flush()
    if old_cover and old_cover != name:
        old_row = (
            session.query(ObservationPhoto)
            .filter(
                ObservationPhoto.observation_id == obs.id,
                ObservationPhoto.photo_path == old_cover,
            )
            .first()
        )
        if old_row is not None:
            _remove_photo_row(session, obs, old_row)
            obs.photo_path = name  # keep the new photo as cover
        else:
            (UPLOAD_DIR / Path(old_cover).name).unlink(missing_ok=True)
    session.commit()
    session.refresh(obs)
    return _obs_to_dict(obs)


@app.post("/api/observations/{obs_id}/photos")
def upload_photos(
    obs_id: int,
    files: list[UploadFile] = File(...),
    session: Session = Depends(get_session),
):
    """Multi-photo upload: attach several photos to a sighting at once.

    Each file has the same 10MB cap (enforced by the ASGI layer on reads —
    we check size while writing) and extension allowlist. The first photo
    ever attached becomes the cover; the cover otherwise stays put.
    """
    obs = session.get(Observation, obs_id)
    if obs is None:
        raise HTTPException(404, "observation not found")
    if not files:
        raise HTTPException(400, "no photos attached")
    names = [_store_upload(f) for f in files]
    for name in names:
        _add_photo_row(session, obs, name)
    session.commit()
    session.refresh(obs)
    return _obs_to_dict(obs)


@app.delete("/api/observations/{obs_id}/photos/{photo_id}")
def delete_photo(
    obs_id: int, photo_id: int, session: Session = Depends(get_session)
):
    obs = session.get(Observation, obs_id)
    if obs is None:
        raise HTTPException(404, "observation not found")
    row = session.get(ObservationPhoto, photo_id)
    if row is None or row.observation_id != obs.id:
        raise HTTPException(404, "photo not found")
    _remove_photo_row(session, obs, row)
    session.commit()
    session.refresh(obs)
    return _obs_to_dict(obs)


@app.get("/api/species/search")
def species_search(q: str = Query(..., min_length=1), per_page: int = Query(10, le=30)):
    """Species autocomplete backed by the iNaturalist taxonomy database."""
    try:
        return {"results": inat.search_taxa(q, per_page=per_page)}
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"iNaturalist lookup failed: {exc}")


MAX_IDENTIFY_BYTES = 10 * 1024 * 1024


VISION_ERROR_TO_CLIENT = {
    "no_key": "not_connected",
    "parse_failed": "vision_parse_failed",
    "api_error": "vision_unreachable",
    "no_animal": "no_animal_found",
}


def _enrich_vision_candidate(candidate: dict) -> dict:
    """Attach iNaturalist canonical data to a vision-model candidate.

    The taxonomy lookup needs no auth. Returns the same card shape the
    /identify UI renders (taxon_id, common_name, scientific_name, rank,
    combined_score, photo_url).
    """
    query = candidate.get("scientific_name") or candidate.get("common_name") or ""
    taxon: dict | None = None
    try:
        matches = inat.search_taxa(query, per_page=3)
    except httpx.HTTPError:
        matches = []
    if matches:
        sci = (candidate.get("scientific_name") or "").lower()
        taxon = next(
            (m for m in matches if (m.get("scientific_name") or "").lower() == sci),
            matches[0],
        )
    return {
        "taxon_id": taxon.get("id") if taxon else None,
        "common_name": (taxon.get("common_name") if taxon else None)
        or candidate.get("common_name"),
        "scientific_name": (taxon.get("scientific_name") if taxon else None)
        or candidate.get("scientific_name"),
        "rank": taxon.get("rank") if taxon else None,
        "vision_score": None,
        "combined_score": candidate.get("confidence"),
        "photo_url": taxon.get("photo_url") if taxon else None,
        "notes": candidate.get("notes"),
    }


@app.post("/api/identify")
def identify_species(file: UploadFile = File(...), session: Session = Depends(get_session)):
    """Photo ID for an uploaded photo.

    Primary path: an OpenRouter vision model names the animal (the
    household's key lives server-side in Settings and never expires);
    iNaturalist's free taxonomy data then enriches each candidate.
    Fallback: the legacy iNaturalist computer-vision endpoint, only when
    INAT_API_TOKEN is configured (its tokens expire after 24 hours).
    With neither configured, suggestions are empty and `error` is
    "not_connected" — the photo is still kept for manual logging.

    Always returns 200 with a `pending_photo` reference.
    """
    ext = Path(file.filename or "").suffix.lower()[:10]
    if ext not in ALLOWED_PHOTO_EXTS:
        raise HTTPException(400, "unsupported image type")
    data = file.file.read(MAX_IDENTIFY_BYTES + 1)
    if len(data) > MAX_IDENTIFY_BYTES:
        raise HTTPException(413, "photo is too large (10 MB max)")
    if not data:
        raise HTTPException(400, "empty photo")
    pending = f"pending_{uuid.uuid4().hex}{ext}"
    with (UPLOAD_DIR / pending).open("wb") as f:
        f.write(data)
    photo_url = f"/photos/{pending}"

    def _result(suggestions, error=None):
        return {
            "suggestions": suggestions,
            "pending_photo": pending,
            "photo_url": photo_url,
            "error": error,
        }

    api_key = get_setting(session, "openrouter_api_key")
    if api_key:
        model = get_setting(session, "vision_model") or vision_id.DEFAULT_VISION_MODEL
        try:
            candidates = vision_id.identify_with_vision(
                data, file.filename or "photo.jpg", api_key, model
            )
        except vision_id.VisionIDError as exc:
            return _result([], error=VISION_ERROR_TO_CLIENT.get(exc.reason, "vision_unreachable"))
        except Exception:  # noqa: BLE001 — model hiccups become a friendly message
            return _result([], error="vision_unreachable")
        return _result([_enrich_vision_candidate(c) for c in candidates])

    if inat.get_api_token():
        try:
            suggestions = inat.identify_image(data, file.filename or "photo.jpg")
        except inat.INatAuthError as exc:
            return _result([], error="not_connected" if exc.reason == "no_token" else "token_expired")
        except httpx.HTTPError:
            return _result([], error="inat_unreachable")
        return _result(suggestions)

    return _result([], error="not_connected")


@app.get("/identify", response_class=HTMLResponse)
def identify_page():
    return pages.identify_page()


ALLOWED_AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".oga", ".m4a", ".webm", ".flac"}


@app.post("/api/identify-audio")
def identify_audio(file: UploadFile = File(...)):
    """Bird sound ID: analyze a recorded/uploaded clip with BirdNET.

    Returns ranked species suggestions (same card shape as photo ID).
    `error` is "not_installed" when the BirdNET engine isn't on this server,
    or "analysis_failed" when the clip couldn't be analyzed.
    """
    ext = Path(file.filename or "").suffix.lower()[:10]
    if ext not in ALLOWED_AUDIO_EXTS:
        raise HTTPException(400, "unsupported audio type")
    data = file.file.read(birdnet.MAX_CLIP_BYTES + 1)
    if len(data) > birdnet.MAX_CLIP_BYTES:
        raise HTTPException(413, "clip is too large (20 MB max)")
    if not data:
        raise HTTPException(400, "empty clip")
    if not birdnet.is_available():
        return {"suggestions": [], "error": "not_installed"}
    try:
        suggestions = birdnet.analyze_clip(data, file.filename or "clip.wav")
    except Exception:  # noqa: BLE001 — model hiccups become a friendly message
        return {"suggestions": [], "error": "analysis_failed"}
    return {"suggestions": suggestions, "error": None}


@app.get("/identify-audio", response_class=HTMLResponse)
def identify_audio_page():
    return pages.identify_audio_page()


# ---------------------------------------------------------------------------
# Life list + stats
# ---------------------------------------------------------------------------


def _observation_day(o: Observation) -> date:
    dt = o.observed_at or o.created_at
    return dt.date() if dt else date.today()


def life_list_rows(session: Session, sort: str = "recent") -> list[dict]:
    """One row per species ever logged: thumbnail, sightings, first/last seen."""
    groups: dict[str, dict] = {}
    for o in session.query(Observation).order_by(Observation.id.asc()).all():
        key = (o.species_name or "").strip().lower() or "__unknown__"
        g = groups.setdefault(
            key,
            {
                "species_name": o.species_name or "Unknown visitor",
                "scientific_names": defaultdict(int),
                "photo_path": None,
                "sightings": 0,
                "individuals": 0,
                "first_seen": None,
                "last_seen": None,
            },
        )
        g["sightings"] += 1
        g["individuals"] += o.count or 1
        if o.scientific_name:
            g["scientific_names"][o.scientific_name] += 1
        if g["photo_path"] is None and o.photo_path:
            g["photo_path"] = o.photo_path
        day = _observation_day(o)
        if g["first_seen"] is None or day < g["first_seen"]:
            g["first_seen"] = day
        if g["last_seen"] is None or day > g["last_seen"]:
            g["last_seen"] = day
    rows = []
    for g in groups.values():
        sci = max(g["scientific_names"], key=g["scientific_names"].get, default=None)
        rows.append(
            {
                "species_name": g["species_name"],
                "scientific_name": sci,
                "photo_url": f"/photos/{g['photo_path']}" if g["photo_path"] else None,
                "sightings": g["sightings"],
                "individuals": g["individuals"],
                "first_seen": g["first_seen"].isoformat() if g["first_seen"] else None,
                "last_seen": g["last_seen"].isoformat() if g["last_seen"] else None,
            }
        )
    if sort == "most":
        rows.sort(key=lambda r: (-r["sightings"], r["species_name"].lower()))
    elif sort == "alpha":
        rows.sort(key=lambda r: r["species_name"].lower())
    else:  # "recent"
        rows.sort(key=lambda r: (r["last_seen"] or "", r["species_name"].lower()), reverse=True)
    return rows


def stats_data(session: Session) -> dict:
    """12-month sighting bars + current-year activity heatmap."""
    counts: dict[date, int] = defaultdict(int)
    for o in session.query(Observation).all():
        counts[_observation_day(o)] += 1

    today = date.today()
    months = []
    for i in range(11, -1, -1):
        # first day of the month, i months back
        m = (today.month - 1 - i) % 12 + 1
        y = today.year - ((today.month - 1 - i) // 12)
        first = date(y, m, 1)
        nxt = date(y + (m == 12), m % 12 + 1, 1)
        total = sum(c for d, c in counts.items() if first <= d < nxt)
        months.append({"label": first.strftime("%b"), "count": total})

    # Year heatmap: Monday-start week columns, one cell per day.
    jan1 = date(today.year, 1, 1)
    start = jan1 - timedelta(days=jan1.weekday())
    dec31 = date(today.year, 12, 31)
    end = dec31 + timedelta(days=(6 - dec31.weekday()))
    weeks: list[list[dict]] = []
    d = start
    while d <= end:
        week = []
        for _ in range(7):
            in_year = d.year == today.year
            week.append(
                {
                    "date": d.isoformat(),
                    "count": counts.get(d, 0) if in_year else -1,  # -1 = pad cell
                }
            )
            d += timedelta(days=1)
        weeks.append(week)
    return {"months": months, "weeks": weeks, "year": today.year}


@app.get("/life-list", response_class=HTMLResponse)
def life_list_page_route(
    sort: str = Query("recent"), session: Session = Depends(get_session)
):
    if sort not in ("recent", "most", "alpha"):
        sort = "recent"
    return pages.life_list_page(life_list_rows(session, sort), sort)


@app.get("/stats", response_class=HTMLResponse)
def stats_page_route(session: Session = Depends(get_session)):
    return pages.stats_page(stats_data(session))


# Range maps + photo gallery
# ---------------------------------------------------------------------------


def _species_own_sightings(
    session: Session, names: set[str]
) -> list[Observation]:
    """Her sightings matching any of the given names (case-insensitive)."""
    lowered = {n.strip().lower() for n in names if n and n.strip()}
    if not lowered:
        return []
    return (
        session.query(Observation)
        .filter(
            or_(
                func.lower(Observation.scientific_name).in_(lowered),
                func.lower(Observation.species_name).in_(lowered),
            )
        )
        .order_by(Observation.observed_at.desc().nullslast(), Observation.id.desc())
        .all()
    )


def _taxon_info(scientific_name: str) -> dict | None:
    """Best-effort taxon card from iNaturalist; None when unreachable/unknown."""
    try:
        matches = inat.search_taxa(scientific_name, per_page=5)
    except Exception:
        return None
    if not matches:
        return None
    lowered = scientific_name.strip().lower()
    for m in matches:
        if (m.get("scientific_name") or "").lower() == lowered:
            return m
    return matches[0]


@app.get("/api/species/range")
def species_range_api(
    scientific_name: str = Query(..., min_length=1),
    session: Session = Depends(get_session),
):
    """JSON range data for a species (cached 7 days). Never 500s."""
    return range_map.get_range(session, scientific_name)


@app.get("/species/{scientific_name:path}", response_class=HTMLResponse)
def species_page_route(
    scientific_name: str, session: Session = Depends(get_session)
):
    name = (scientific_name or "").strip()
    taxon = _taxon_info(name) if name else None
    names = {name}
    if taxon and taxon.get("common_name"):
        names.add(taxon["common_name"])
    if taxon and taxon.get("scientific_name"):
        names.add(taxon["scientific_name"])
    rng = range_map.get_range(session, name)
    own = _species_own_sightings(session, names)
    # Her own mappable sightings: distinct brown markers on the map.
    own_points = [
        {
            "lat": o.latitude,
            "lng": o.longitude,
            "label": (o.location_name or "Your sighting"),
        }
        for o in own
        if o.latitude is not None and o.longitude is not None
    ]
    return pages.species_page(
        taxon=taxon,
        range_data=rng,
        own_points=own_points,
        sightings=[_obs_to_dict(o) for o in own],
        display_name=name or "Unknown species",
    )


def _gallery_species_options(session: Session) -> list[str]:
    rows = (
        session.query(Observation.species_name)
        .filter(Observation.photo_path.isnot(None))
        .filter(Observation.species_name.isnot(None))
        .distinct()
        .all()
    )
    return sorted({r[0] for r in rows if r[0]}, key=str.lower)


@app.get("/gallery", response_class=HTMLResponse)
def gallery_page_route(
    species: str | None = Query(None),
    q: str | None = Query(None),
    session: Session = Depends(get_session),
):
    query = (
        session.query(Observation)
        .filter(Observation.photo_path.isnot(None))
        .order_by(Observation.observed_at.desc().nullslast(), Observation.id.desc())
    )
    query = _apply_observation_search(query, q, False)
    if species and species.strip():
        query = query.filter(
            func.lower(Observation.species_name) == species.strip().lower()
        )
    items = [_obs_to_dict(o) for o in query.all()]
    return pages.gallery_page(
        items,
        species_options=_gallery_species_options(session),
        selected_species=species or "",
        q=q or "",
    )


# ---------------------------------------------------------------------------
# Sightings map — pins for HER sightings that have a location
# ---------------------------------------------------------------------------


def _date_label(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%b %d, %Y")
    except ValueError:
        return iso


def _mapped_species_options(session: Session) -> list[str]:
    rows = (
        session.query(Observation.species_name)
        .filter(Observation.latitude.isnot(None), Observation.longitude.isnot(None))
        .filter(Observation.species_name.isnot(None))
        .distinct()
        .all()
    )
    return sorted({r[0] for r in rows if r[0]}, key=str.lower)


@app.get("/map", response_class=HTMLResponse)
def map_page_route(
    species: str | None = Query(None), session: Session = Depends(get_session)
):
    query = session.query(Observation).filter(
        Observation.latitude.isnot(None), Observation.longitude.isnot(None)
    )
    if species and species.strip():
        query = query.filter(
            func.lower(Observation.species_name) == species.strip().lower()
        )
    pins = []
    for o in query.order_by(Observation.id.desc()).all():
        pins.append(
            {
                "lat": o.latitude,
                "lng": o.longitude,
                "species": o.species_name or "Unknown visitor",
                "scientific": o.scientific_name or "",
                "date": _date_label(o.observed_at.isoformat() if o.observed_at else None),
                "thumb": f"/photos/{o.photo_path}" if o.photo_path else None,
                "href": (
                    f"/observations?q={quote(o.species_name)}"
                    if o.species_name
                    else "/observations"
                ),
            }
        )
    return pages.map_page(
        pins,
        species_options=_mapped_species_options(session),
        selected_species=species or "",
    )


# ---------------------------------------------------------------------------
# "Around you right now" — species being seen near home
# ---------------------------------------------------------------------------


@app.get("/api/nearby")
def nearby_api(session: Session = Depends(get_session)):
    home = get_home_location(session)
    if home["latitude"] is None or home["longitude"] is None:
        return {
            "taxa": [],
            "from_cache": False,
            "error": "no_home_location",
            "home": home,
        }
    data = nearby_mod.get_nearby(session, home["latitude"], home["longitude"])
    data["home"] = home
    return data


@app.get("/nearby", response_class=HTMLResponse)
def nearby_page_route(session: Session = Depends(get_session)):
    home = get_home_location(session)
    if home["latitude"] is None or home["longitude"] is None:
        return pages.nearby_page(home=home, taxa=[], error="no_home_location")
    data = nearby_mod.get_nearby(session, home["latitude"], home["longitude"])
    return pages.nearby_page(
        home=home, taxa=data["taxa"], error=data["error"], from_cache=data["from_cache"]
    )


# ---------------------------------------------------------------------------
# Wishlist — species she'd love to find
# ---------------------------------------------------------------------------


class WishlistIn(BaseModel):
    scientific_name: str | None = None
    common_name: str | None = None
    taxon_id: int | None = None
    notes: str | None = None


def _wishlist_seen(session: Session, item: Wishlist) -> bool:
    """Seen ✓ is derived at read time: any sighting matching the name."""
    names = {
        n.strip().lower()
        for n in (item.scientific_name, item.common_name)
        if n and n.strip()
    }
    if not names:
        return False
    return (
        session.query(Observation.id)
        .filter(
            or_(
                func.lower(Observation.scientific_name).in_(names),
                func.lower(Observation.species_name).in_(names),
            )
        )
        .first()
        is not None
    )


def _wishlist_to_dict(session: Session, item: Wishlist) -> dict:
    return {
        "id": item.id,
        "scientific_name": item.scientific_name,
        "common_name": item.common_name,
        "taxon_id": item.taxon_id,
        "notes": item.notes,
        "seen": _wishlist_seen(session, item),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@app.get("/api/wishlist")
def list_wishlist(session: Session = Depends(get_session)):
    items = session.query(Wishlist).order_by(Wishlist.id.desc()).all()
    return {"wishlist": [_wishlist_to_dict(session, w) for w in items]}


@app.post("/api/wishlist")
def add_wishlist(payload: WishlistIn, session: Session = Depends(get_session)):
    sci = (payload.scientific_name or "").strip() or None
    common = (payload.common_name or "").strip() or None
    if not (sci or common):
        raise HTTPException(400, "name a species first")
    if sci:
        dupe = (
            session.query(Wishlist)
            .filter(func.lower(Wishlist.scientific_name) == sci.lower())
            .first()
        )
        if dupe:
            raise HTTPException(409, "already on your wishlist")
    item = Wishlist(
        scientific_name=sci,
        common_name=common,
        taxon_id=payload.taxon_id,
        notes=(payload.notes or "").strip() or None,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return _wishlist_to_dict(session, item)


@app.delete("/api/wishlist/{item_id}")
def remove_wishlist(item_id: int, session: Session = Depends(get_session)):
    item = session.get(Wishlist, item_id)
    if item is None:
        raise HTTPException(404, "wishlist item not found")
    session.delete(item)
    session.commit()
    return {"deleted": item_id}


@app.get("/wishlist", response_class=HTMLResponse)
def wishlist_page_route(session: Session = Depends(get_session)):
    items = session.query(Wishlist).order_by(Wishlist.id.desc()).all()
    # Thumbnails come from the free iNaturalist taxonomy lookup; per-name
    # memoized so a long list doesn't repeat queries. Never breaks the page.
    thumb_cache: dict[str, dict | None] = {}

    def _thumb_for(item: Wishlist) -> dict | None:
        name = (item.scientific_name or item.common_name or "").strip()
        if not name:
            return None
        if name not in thumb_cache:
            try:
                thumb_cache[name] = _taxon_info(name)
            except Exception:  # noqa: BLE001 — thumbnails are a nicety
                thumb_cache[name] = None
        return thumb_cache[name]

    cards = []
    for item in items:
        d = _wishlist_to_dict(session, item)
        taxon = _thumb_for(item)
        d["photo_url"] = (taxon or {}).get("photo_url")
        d["range_href"] = (
            f"/species/{item.scientific_name}" if item.scientific_name else None
        )
        cards.append(d)
    return pages.wishlist_page(cards)


# ---------------------------------------------------------------------------
# Service worker (offline mode)
# ---------------------------------------------------------------------------

SW_JS_PATH = Path(__file__).resolve().parent / "static" / "js" / "sw.js"


@app.get("/sw.js")
def service_worker():
    """The offline service worker (registered from the layout)."""
    return FileResponse(str(SW_JS_PATH), media_type="application/javascript")
