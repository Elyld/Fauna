"""Capture the Settings page showing the vision-model dropdown.

Serves /api/openrouter-models from a canned catalog via route interception,
so the dropdown populates deterministically. Run while the app serves on
:4001 (any data dir works — Settings renders without sightings).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

for _var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_var, None)

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:4001"
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
CHROME = str(Path.home() / "pw-chrome" / "chrome-linux64" / "chrome")

CATALOG = {
    "models": [
        {"id": "google/gemma-4-31b-it:free", "name": "Gemma 4 31B", "free": True},
        {"id": "qwen/qwen2.5-vl-72b-instruct:free", "name": "Qwen2.5-VL 72B Instruct", "free": True},
        {"id": "openai/gpt-4o-mini", "name": "GPT-4o mini", "free": False},
    ]
}


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME)
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        def _intercept(route):
            if route.request.url.endswith("/api/openrouter-models"):
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps(CATALOG).encode(),
                )
            else:
                route.continue_()

        page.route("**/*", _intercept)
        page.goto(f"{BASE}/settings", wait_until="networkidle")
        # Wait until the dropdown is populated (2 free models + Custom…).
        page.wait_for_function(
            "document.querySelectorAll('#vision-model-select option').length >= 3",
            timeout=15000,
        )
        card = page.locator(".form-card").first
        card.screenshot(path=str(OUT / "settings.png"))
        browser.close()
    print("saved", OUT / "settings.png")


if __name__ == "__main__":
    main()
