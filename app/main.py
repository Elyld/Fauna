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

from app import inat
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
        "created_at": o.created_at.isoformat() if o.created_at else None,
    }


@app.get("/", response_class=HTMLResponse)
def index():
    return f"""<!doctype html><html><head><title>{APP_NAME}</title></head>
<body style="font-family:sans-serif;max-width:640px;margin:4rem auto;padding:0 1rem">
<h1>{APP_NAME} 🦌</h1>
<p>Wildlife observation journal — v{VERSION} scaffold.</p>
<ul>
<li><a href="/api/health">API health</a></li>
<li><a href="/api/observations">Observations</a></li>
<li><a href="/api/species/search?q=robin">Species search (e.g. robin)</a></li>
<li><a href="/docs">API docs</a></li>
</ul></body></html>"""


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
    obs = Observation(**payload.model_dump())
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
