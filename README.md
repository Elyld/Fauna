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

## Roadmap (Phase 1)

- [x] Observation logging API (species, count, date/time, GPS, location name, notes)
- [x] Photo uploads served at `/photos`
- [x] Species search/autocomplete backed by iNaturalist (`GET /api/species/search?q=robin`)
- [x] Pink-themed web UI: home (`/`), observations (`/observations`), log-a-sighting form with iNaturalist autocomplete (`/observations/new`)
- [x] Photo ID (`/identify`): upload a photo → iNaturalist computer-vision suggestions → confirm → prefilled sighting form (needs `INAT_API_TOKEN`, see below)
- [ ] Bird sound ID (`/identify-audio`): record/upload a clip → BirdNET analysis → suggestions → prefilled sighting form
- [ ] Range maps per species (iNaturalist/GBIF occurrence data)
- [ ] Life list + stats
- [ ] Photo gallery
- [ ] Mobile-friendly quick-log

Demo data + screenshots: with the app running, `scripts/seed_demo.py` seeds five charming observations (real iNaturalist names and photos) via the API, and `scripts/screenshots.py` captures `docs/screenshots/` with Chrome for Testing.

## Species data

Species identification runs on the public [iNaturalist API](https://api.inaturalist.org/v1/docs/) — the open equivalent of what powers Merlin: a taxonomy database covering essentially all wildlife, plus millions of observations for range/location data. No API key needed for the read endpoints used here. eBird/GBIF are candidates for later phases.

## Photo ID setup

The 🔍 Identify page scores photos with iNaturalist's computer vision
(`POST /v1/computervision/score_image`). That endpoint requires an API token:

1. Log in at [inaturalist.org](https://www.inaturalist.org) and register an
   OAuth application (any name, e.g. "Fauna").
2. Get a token from <https://www.inaturalist.org/users/api_token>.
3. Set it as `INAT_API_TOKEN` in the app's environment (e.g. in
   `docker-compose.yml`) and restart.

Heads-up: iNaturalist tokens expire after 24 hours, so this is a daily
copy-paste until iNaturalist offers longer-lived tokens. Without a token the
Identify page still works — it saves the photo and falls back to manual entry
with a friendly notice instead of suggestions.

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
