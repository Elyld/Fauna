"""Capture Fauna demo screenshots (1280x800) into docs/screenshots/.

Run while the app is serving on :4001 with demo data seeded.
Uses vanilla Chrome for Testing, no proxy.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Proxy handling for this sandbox: localhost traffic must NOT use the proxy,
# external traffic (iNaturalist) MUST. So: stash the proxy vars, sanitize
# NO_PROXY (bracketed IPv6 literals crash httpx's parsing), and only restore
# the proxy vars around external calls.
_SAVED_PROXY = {
    v: os.environ.get(v)
    for v in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy")
}
for _var in _SAVED_PROXY:
    os.environ.pop(_var, None)
for _var in ("NO_PROXY", "no_proxy"):
    _val = os.environ.get(_var)
    if _val and "[" in _val:
        os.environ[_var] = ",".join(p for p in _val.split(",") if "[" not in p)


def _with_proxy():
    """Context manager restoring proxy env for external calls."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        for v, val in _SAVED_PROXY.items():
            if val:
                os.environ[v] = val
        try:
            yield
        finally:
            for v in _SAVED_PROXY:
                os.environ.pop(v, None)

    return _ctx()

import httpx  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:4001"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
CHROME = str(Path.home() / "pw-chrome" / "chrome-linux64" / "chrome")

CANNED_SUGGESTIONS = [
    {
        "taxon_id": 46017,
        "common_name": "Eastern Gray Squirrel",
        "scientific_name": "Sciurus carolinensis",
        "rank": "species",
        "vision_score": 0.96,
        "combined_score": 0.93,
        "photo_url": "https://static.inaturalist.org/photos/demo/squirrel-medium.jpg",
    },
    {
        "taxon_id": 46019,
        "common_name": "Fox Squirrel",
        "scientific_name": "Sciurus niger",
        "rank": "species",
        "vision_score": 0.71,
        "combined_score": 0.68,
        "photo_url": "https://static.inaturalist.org/photos/demo/fox-medium.jpg",
    },
    {
        "taxon_id": 47043,
        "common_name": "American Red Squirrel",
        "scientific_name": "Tamiasciurus hudsonicus",
        "rank": "species",
        "vision_score": 0.42,
        "combined_score": 0.39,
        "photo_url": "https://static.inaturalist.org/photos/demo/red-medium.jpg",
    },
]


def main() -> None:
    # Get a real pending_photo reference via the API (works without a token;
    # it just reports photo ID as not connected).
    demo_photo = next((Path("photos").glob("*.jp*g")))
    demo_wav = Path.home() / "workspace" / ".probe" / "audio" / "soundscape.wav"
    demo_photos = sorted(Path("photos").glob("*.jp*g"))
    with httpx.Client(timeout=30.0) as c:
        up = c.post(
            f"{BASE}/api/identify",
            files={"file": (demo_photo.name, demo_photo.read_bytes(), "image/jpeg")},
        ).json()

    # Map canned suggestion thumbnails to the REAL taxon photos from iNaturalist
    # (sandbox Chromium can't fetch externals, so we serve them via interception).
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from app import inat as _inat

    thumb_map = {}
    with _with_proxy():
        for s in CANNED_SUGGESTIONS:
            try:
                matches = _inat.search_taxa(s["common_name"], per_page=3)
                match = next((m for m in matches if m.get("photo_url")), None)
                if match:
                    with httpx.Client(timeout=30.0) as dl:
                        img = dl.get(match["photo_url"]).content
                    thumb_map[s["photo_url"]] = img
                    print(f"thumbnail: {s['common_name']} ({len(img)//1024} KB)")
            except Exception as exc:  # noqa: BLE001 — screenshot-only nicety
                print(f"thumbnail SKIP {s['common_name']}: {exc}")

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        page.goto(f"{BASE}/", wait_until="networkidle")
        page.screenshot(path=str(OUT / "home.png"))
        print("home.png")

        page.goto(f"{BASE}/observations", wait_until="networkidle")
        page.screenshot(path=str(OUT / "observations.png"))
        print("observations.png")

        # Identify page: intercept /api/identify with canned suggestions so the
        # screenshot shows the confirm step (no iNaturalist token in sandbox).
        def _fulfill(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=(
                    '{"suggestions": %s, "pending_photo": "%s", '
                    '"photo_url": "%s", "error": null}'
                    % (
                        __import__("json").dumps(CANNED_SUGGESTIONS),
                        up["pending_photo"],
                        up["photo_url"],
                    )
                ),
            )

        page.route("**/api/identify", _fulfill)
        page.route(
            "https://static.inaturalist.org/photos/demo/*",
            lambda route: route.fulfill(
                status=200,
                content_type="image/jpeg",
                body=thumb_map.get(route.request.url, b""),
            ),
        )
        page.goto(f"{BASE}/identify", wait_until="networkidle")
        page.set_input_files("#photo-input", str(demo_photo))
        page.click("#identify-btn")
        page.wait_for_selector(".suggestion", timeout=15000)
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "identify.png"))
        print("identify.png")
        page.unroute("**/api/identify")

        # Sound ID page: same interception trick for /api/identify-audio.
        canned_audio = [
            {
                "taxon_id": None,
                "common_name": "Black-capped Chickadee",
                "scientific_name": "Poecile atricapillus",
                "rank": "species",
                "vision_score": None,
                "combined_score": 0.8141,
                "photo_url": "https://static.inaturalist.org/photos/demo/abird1.jpg",
            },
            {
                "taxon_id": None,
                "common_name": "American Goldfinch",
                "scientific_name": "Spinus tristis",
                "rank": "species",
                "vision_score": None,
                "combined_score": 0.5028,
                "photo_url": "https://static.inaturalist.org/photos/demo/abird2.jpg",
            },
        ]
        with _with_proxy():
            for s in canned_audio:
                try:
                    matches = _inat.search_taxa(s["common_name"], per_page=3)
                    match = next((m for m in matches if m.get("photo_url")), None)
                    if match:
                        with httpx.Client(timeout=30.0) as dl:
                            thumb_map[s["photo_url"]] = dl.get(match["photo_url"]).content
                        print(f"audio thumbnail: {s['common_name']}")
                except Exception as exc:  # noqa: BLE001
                    print(f"audio thumbnail SKIP {s['common_name']}: {exc}")

        def _afulfill(route):
            route.fulfill(
                status=200,
                content_type="application/json",
                body=__import__("json").dumps(
                    {"suggestions": canned_audio, "error": None}
                ),
            )

        page.route("**/api/identify-audio", _afulfill)
        page.goto(f"{BASE}/identify-audio", wait_until="networkidle")
        page.set_input_files("#audio-input", str(demo_wav))
        page.click("#aidentify-btn")
        page.wait_for_selector(".suggestion", timeout=15000)
        page.wait_for_timeout(500)
        page.screenshot(path=str(OUT / "identify-audio.png"))
        print("identify-audio.png")
        page.unroute("**/api/identify-audio")

        page.goto(f"{BASE}/observations/new", wait_until="networkidle")
        page.click("#species")
        page.type("#species", "squirrel", delay=60)
        page.wait_for_selector(".autocomplete.open", timeout=15000)
        page.wait_for_timeout(800)  # let thumbnails load
        page.screenshot(path=str(OUT / "new-observation.png"))
        print("new-observation.png")

        browser.close()


if __name__ == "__main__":
    main()
