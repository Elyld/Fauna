# Fauna 🦌

**Working name — it will change.** A wildlife observation journal: think the Merlin bird app, but for all wildlife — squirrels, birds, bunnies, you name it. Log sightings, identify species, and track a life list, all self-hosted.

Built for Josh's wife. Same bones as [Verdant](https://github.com/Elyld/Verdant): FastAPI + SQLite, Docker on your own server, nothing in the cloud.

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
- [ ] Photo-based ID suggestions (iNaturalist computer vision)
- [ ] Range maps per species (iNaturalist/GBIF occurrence data)
- [ ] Life list + stats
- [ ] Photo gallery + frontend pages
- [ ] Mobile-friendly quick-log

## Species data

Species identification runs on the public [iNaturalist API](https://api.inaturalist.org/v1/docs/) — the open equivalent of what powers Merlin: a taxonomy database covering essentially all wildlife, plus millions of observations for range/location data. No API key needed for the read endpoints used here. eBird/GBIF are candidates for later phases.

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
