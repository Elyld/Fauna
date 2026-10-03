"""Capture Fauna demo screenshots (1280x800) into docs/screenshots/.

Run while the app is serving on :4001 with demo data seeded.
Uses vanilla Chrome for Testing, no proxy.
"""
from __future__ import annotations

import os
from pathlib import Path

# Keep Playwright's Chromium out of proxy env weirdness entirely.
for _var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy"):
    os.environ.pop(_var, None)

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:4001"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
CHROME = str(Path.home() / "pw-chrome" / "chrome-linux64" / "chrome")


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        page.goto(f"{BASE}/", wait_until="networkidle")
        page.screenshot(path=str(OUT / "home.png"))
        print("home.png")

        page.goto(f"{BASE}/observations", wait_until="networkidle")
        page.screenshot(path=str(OUT / "observations.png"))
        print("observations.png")

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
