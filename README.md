# Fauna 🦌

**Working name — it will change.** A wildlife observation journal: think the Merlin bird app, but for all wildlife — squirrels, birds, bunnies, you name it. Log sightings, identify species, and track a life list, all self-hosted.

A wildlife observation journal built as a gift. Same bones as [Verdant](https://github.com/Elyld/Verdant): FastAPI + SQLite, Docker on your own server, nothing in the cloud.

## Quick start

```bash
docker compose up -d
# open http://localhost:4001  (or set FAUNA_PORT in your environment)
```

Local dev:

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
PYTHONPATH=. .venv/bin/python -m pytest -q
PYTHONPATH=. .venv/bin/uvicorn app.main:app --reload --port 4001
```

Data lives in `./data` (SQLite) and `./photos` (observation pictures) — both are Docker volumes, so they survive rebuilds.

## Deploying in Dockge (GHCR image)

Fauna publishes a ready-made image to GitHub Container Registry on every push to `main`, so Dockge (or Portainer, or plain compose) can run it with zero build step:

```yaml
services:
  fauna:
    image: ghcr.io/elyld/fauna:latest
    container_name: fauna-wildlife-journal
    restart: unless-stopped
    ports:
      - "${FAUNA_PORT:-4001}:8000"
    environment:
      FAUNA_DATA_DIR: /data
      FAUNA_UPLOAD_DIR: /photos
      FAUNA_DATABASE_URL: sqlite:////data/fauna.db
    volumes:
      - ./data:/data
      - ./photos:/photos
```

Paste that into a new Dockge stack (or just use this repo's `docker-compose.yml` as-is — it already pulls the image), hit deploy, and open the host's port 4001. Updating is `docker compose pull && docker compose up -d`, or Dockge's update button — your sightings live in the bind-mounted `./data` and `./photos` folders, not the image, so nothing is lost.

## Roadmap (Phase 1)

- [x] Observation logging API (species, count, date/time, GPS, location name, notes)
- [x] Photo uploads served at `/photos`
- [x] Species search/autocomplete backed by iNaturalist (`GET /api/species/search?q=robin`)
- [x] Pink-themed web UI: home (`/`), observations (`/observations`), log-a-sighting form with iNaturalist autocomplete (`/observations/new`)
- [x] Photo ID (`/identify`): upload a photo → vision-model suggestions → confirm → prefilled sighting form (needs an OpenRouter key in Settings, see below)
- [x] Bird sound ID (`/identify-audio`): record/upload a clip → BirdNET analysis → suggestions → prefilled sighting form
- [ ] Range maps per species (iNaturalist/GBIF occurrence data)
- [ ] Life list + stats
- [ ] Photo gallery
- [x] Mobile-friendly quick-log: responsive pages, bottom tab bar, camera-first photo capture, installable PWA

## Mobile + PWA

Every page is responsive down to phone widths: the desktop nav gives way to a
bottom tab bar (Home · Sightings · Identify · Sound), the sighting form leads
with a big photo button and tucks the rest into a "More details" section, and
inputs stay at 16px so iOS doesn't auto-zoom.

Fauna is installable as an app: it serves a `manifest.json` (`/manifest.json`)
with a teddy-bear icon, theme color, and standalone display — on Android use
Chrome's "Add to Home screen" / "Install app", on iOS use Safari's Share →
"Add to Home Screen".

Camera capture: photo inputs use `capture="environment"`, so on phones the
camera opens directly (gallery is still offered by the OS picker). Offline
support (service worker + cached sightings) is future work — the app needs a
connection for species search, photo ID, and sound ID.

Demo data + screenshots: with the app running, `scripts/seed_demo.py` seeds five charming observations (real iNaturalist names and photos) via the API, and `scripts/screenshots.py` captures `docs/screenshots/` with Chrome for Testing.

## Species data

Species identification runs on the public [iNaturalist API](https://api.inaturalist.org/v1/docs/) — the open equivalent of what powers Merlin: a taxonomy database covering essentially all wildlife, plus millions of observations for range/location data. No API key needed for the read endpoints used here. eBird/GBIF are candidates for later phases.

## Photo ID setup

The 🔍 Identify page names the animal in a photo with a vision model through
[OpenRouter](https://openrouter.ai). iNaturalist's own computer-vision
endpoint isn't used because it needs a per-user token that expires every 24
hours (a daily copy-paste chore); an OpenRouter key is pasted once and never
expires.

Setup (one time):

1. Open Fauna's ⚙️ Settings page.
2. Paste an OpenRouter API key (the same kind Verdant uses) and save. The key
   is stored on the server and is never shown back in the UI.
3. The vision model defaults to `google/gemma-4-31b-it:free` — a free model,
   so photo ID costs nothing. Free models can be slow or rate-limited; if one
   ever flakes, a cheap paid vision model costs a fraction of a cent per photo
   and can be typed into the same Settings field.

How it works: the model names the animal (up to 3 ranked guesses with
confidence), iNaturalist's free no-login taxonomy data attaches canonical
names, thumbnails, and links, and she confirms the pick before anything is
saved — the AI is a suggester, never the decider.

Legacy fallback: if no OpenRouter key is configured but `INAT_API_TOKEN` is
set in the environment, the Identify page falls back to iNaturalist computer
vision (tokens expire after 24 hours, so this needs daily renewing). With
neither configured, the page saves the photo and offers manual entry.

## Sound ID setup

The 🎵 Sound ID page analyzes bird recordings with
[BirdNET-Analyzer](https://github.com/birdnet-team/birdnet-analyzer)
(Merlin Sound-ID style, but server-side: she records or uploads a short clip,
the server analyzes it a few seconds later — live real-time listening isn't
feasible in a web v1).

- Install: `pip install -r requirements.txt` includes `birdnet-analyzer`.
  It's heavy (~700MB — TensorFlow) and downloads a ~230MB model on first
  analysis (cached in the package's `checkpoints/` dir; the Dockerfile
  pre-downloads it at build time). The app runs fine without it: the Sound ID
  page then explains it's not set up instead of erroring.
- Phone recordings are usually `webm`/`mp4` — BirdNET reads those via
  `ffmpeg`, which the Dockerfile installs. (Plain `wav` needs nothing.)
- Non-bird sounds the model knows (engine noise, sirens…) are filtered out
  of the suggestions automatically.

## Tests

Live-network tests are opt-in (same convention as Verdant's deselected live tests):

```bash
# default: skips the live iNaturalist test
PYTHONPATH=. .venv/bin/python -m pytest -q
# include it:
FAUNA_LIVE_TESTS=1 PYTHONPATH=. .venv/bin/python -m pytest -q
```

## Renaming

The app name lives in exactly three places: `APP_NAME` in `app/version.py`, this README, and the `docker-compose.yml` service/container names. Update those and the rename is done.
