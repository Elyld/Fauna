"""Fauna — wildlife observation journal (working name; will change)."""
from __future__ import annotations

import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import birdnet
from app import inat
from app import pages
from app.database import UPLOAD_DIR, get_session, init_db
from app.models import Observation
from app.version import APP_NAME, VERSION


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
        "needs_id": bool(o.needs_id) if o.needs_id is not None else False,
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


@app.get("/", response_class=HTMLResponse)
def index(session: Session = Depends(get_session)):
    obs = session.query(Observation).order_by(Observation.id.desc()).all()
    dicts = [_obs_to_dict(o) for o in obs]
    species = {o["species_name"] for o in dicts if o.get("species_name")}
    return pages.home_page(len(dicts), len(species), dicts[:4])


@app.get("/observations", response_class=HTMLResponse)
def observations_page(session: Session = Depends(get_session)):
    obs = session.query(Observation).order_by(Observation.id.desc()).all()
    return pages.observations_page([_obs_to_dict(o) for o in obs])


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


@app.get("/api/observations")
def list_observations(session: Session = Depends(get_session)):
    obs = session.query(Observation).order_by(Observation.id.desc()).all()
    return {"observations": [_obs_to_dict(o) for o in obs]}


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
    return _obs_to_dict(obs)


@app.delete("/api/observations/{obs_id}")
def delete_observation(obs_id: int, session: Session = Depends(get_session)):
    obs = session.get(Observation, obs_id)
    if obs is None:
        raise HTTPException(404, "observation not found")
    session.delete(obs)
    session.commit()
    return {"deleted": obs_id}


@app.post("/api/observations/{obs_id}/photo")
def upload_photo(
    obs_id: int, file: UploadFile = File(...), session: Session = Depends(get_session)
):
    obs = session.get(Observation, obs_id)
    if obs is None:
        raise HTTPException(404, "observation not found")
    ext = Path(file.filename or "").suffix.lower()[:10]
    if ext not in ALLOWED_PHOTO_EXTS:
        raise HTTPException(400, "unsupported image type")
    name = f"{uuid.uuid4().hex}{ext}"
    with (UPLOAD_DIR / name).open("wb") as f:
        shutil.copyfileobj(file.file, f)
    if obs.photo_path:
        (UPLOAD_DIR / obs.photo_path).unlink(missing_ok=True)
    obs.photo_path = name
    session.commit()
    return _obs_to_dict(obs)


@app.get("/api/species/search")
def species_search(q: str = Query(..., min_length=1), per_page: int = Query(10, le=30)):
    """Species autocomplete backed by the iNaturalist taxonomy database."""
    try:
        return {"results": inat.search_taxa(q, per_page=per_page)}
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"iNaturalist lookup failed: {exc}")


MAX_IDENTIFY_BYTES = 10 * 1024 * 1024


@app.post("/api/identify")
def identify_species(file: UploadFile = File(...)):
    """Photo ID: score an uploaded photo with iNaturalist computer vision.

    Always returns 200 with a `pending_photo` reference (the uploaded file,
    kept server-side so the sighting form can claim it later). `suggestions`
    is empty and `error` is set when photo ID isn't connected or iNaturalist
    is unreachable — the caller should fall back to manual entry.
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

    try:
        suggestions = inat.identify_image(data, file.filename or "photo.jpg")
    except inat.INatAuthError as exc:
        # Friendly, non-technical: the household admin connects this once.
        return _result([], error="not_connected" if exc.reason == "no_token" else "token_expired")
    except httpx.HTTPError:
        return _result([], error="inat_unreachable")
    return _result(suggestions)


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
