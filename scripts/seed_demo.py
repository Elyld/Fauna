"""Seed charming demo observations for screenshots.

Uses the real iNaturalist taxonomy + photos via the app's own API:
  1. Clears existing observations.
  2. For each species, searches iNaturalist for the top taxon match,
     downloads its default photo, creates the observation, uploads the photo.

Run while the app is serving:
    ~/workspace/fauna/.venv/bin/python scripts/seed_demo.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Sandbox-only workaround: this runtime's NO_PROXY contains bracketed IPv6
# literals that crash httpx's proxy-env parsing. Strip them (real deployments
# don't have these entries).
for _var in ("NO_PROXY", "no_proxy"):
    _val = os.environ.get(_var)
    if _val:
        os.environ[_var] = ",".join(p for p in _val.split(",") if "[" not in p)

import httpx  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import inat  # noqa: E402

BASE = os.environ.get("FAUNA_BASE_URL", "http://127.0.0.1:4001")

SPECIES = [
    {
        "query": "Eastern Gray Squirrel",
        "count": 3,
        "days_ago": 1,
        "location_name": "Backyard oak",
        "notes": "Chasing each other around the trunk — one looked very smug about an acorn.",
    },
    {
        "query": "American Robin",
        "count": 2,
        "days_ago": 3,
        "location_name": "Front lawn",
        "notes": "Tug-of-war with an earthworm at dawn. The worm lost.",
    },
    {
        "query": "Eastern Cottontail",
        "count": 1,
        "days_ago": 5,
        "location_name": "Garden bed edge",
        "notes": "Frozen mid-nibble, pretending to be a statue. It was not convincing.",
    },
    {
        "query": "Monarch Butterfly",
        "count": 4,
        "days_ago": 8,
        "location_name": "Milkweed patch",
        "notes": "Drifting between the blooms like confetti.",
    },
    {
        "query": "Northern Cardinal",
        "count": 2,
        "days_ago": 12,
        "location_name": "Backyard feeder",
        "notes": "The pair showed up together, as always. He let her eat first.",
    },
]


def main() -> None:
    with httpx.Client(timeout=30.0) as client:
        # Clear any existing observations for a deterministic demo.
        existing = client.get(f"{BASE}/api/observations").json()["observations"]
        for o in existing:
            client.delete(f"{BASE}/api/observations/{o['id']}")
        print(f"cleared {len(existing)} existing observations")

        for spec in SPECIES:
            matches = inat.search_taxa(spec["query"], per_page=5)
            match = next((m for m in matches if m.get("photo_url")), None)
            if match is None:
                print(f"SKIP {spec['query']}: no iNaturalist match with photo")
                continue
            observed_at = (datetime.now() - timedelta(days=spec["days_ago"])).replace(
                hour=9, minute=30, second=0, microsecond=0
            )
            payload = {
                "species_name": match["common_name"] or match["scientific_name"],
                "scientific_name": match["scientific_name"],
                "count": spec["count"],
                "observed_at": observed_at.isoformat(),
                "location_name": spec["location_name"],
                "notes": spec["notes"],
            }
            created = client.post(f"{BASE}/api/observations", json=payload).json()
            obs_id = created["id"]

            photo_url = match["photo_url"]
            ext = Path(photo_url.split("?")[0]).suffix.lower() or ".jpg"
            if ext not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
                ext = ".jpg"
            img = client.get(photo_url).content
            files = {"file": (f"demo{ext}", img, f"image/{ext.lstrip('.')}")}
            up = client.post(f"{BASE}/api/observations/{obs_id}/photo", files=files)
            up.raise_for_status()
            print(
                f"seeded #{obs_id}: {payload['species_name']} "
                f"({payload['scientific_name']}) ×{spec['count']} — photo {len(img)//1024} KB"
            )


if __name__ == "__main__":
    main()
