"""Capture Fauna mobile screenshots (390x844) into docs/screenshots/.

Run while the app is serving on :4001 with demo data seeded.
Uses vanilla Chrome for Testing, no proxy.
"""
from __future__ import annotations

import os
from pathlib import Path

# Proxy handling for this sandbox: localhost traffic must NOT use the proxy.
for _var in (
    "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy",
    "ALL_PROXY", "all_proxy",
):
    os.environ.pop(_var, None)
for _var in ("NO_PROXY", "no_proxy"):
    _val = os.environ.get(_var)
    if _val and "[" in _val:
        os.environ[_var] = ",".join(p for p in _val.split(",") if "[" not in p)

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:4001"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
CHROME = str(Path.home() / "pw-chrome" / "chrome-linux64" / "chrome")

SHOTS = [
    ("mobile-home.png", "/"),
    ("mobile-observations.png", "/observations"),
    ("mobile-identify.png", "/identify"),
    ("mobile-new.png", "/observations/new"),
]


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 390, "height": 844})
        for name, path in SHOTS:
            page.goto(f"{BASE}{path}", wait_until="networkidle")
            # Assert no horizontal overflow while we're here.
            overflow = page.evaluate(
                "document.documentElement.scrollWidth - document.documentElement.clientWidth"
            )
            assert overflow <= 1, f"{path} overflows by {overflow}px"
            page.screenshot(path=str(OUT / name))
            print(name, "ok")
        # One desktop re-capture to prove desktop is unchanged.
        desk = browser.new_page(viewport={"width": 1280, "height": 800})
        desk.goto(f"{BASE}/", wait_until="networkidle")
        desk.screenshot(path=str(OUT / "home.png"))
        print("home.png (desktop re-capture) ok")
        browser.close()


if __name__ == "__main__":
    main()
