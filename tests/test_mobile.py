"""Mobile-web tests: viewport/PWA tags, camera capture, tab bar, quick-log layout,
and no horizontal overflow at phone width.

Run:  cd ~/workspace/fauna && PYTHONPATH=. .venv/bin/python -m pytest -q
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="fauna-mobile-test-"))
os.environ.setdefault("FAUNA_DATA_DIR", str(TMP / "data"))
os.environ.setdefault("FAUNA_UPLOAD_DIR", str(TMP / "photos"))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import UPLOAD_DIR, init_db  # noqa: E402
from app.main import app  # noqa: E402

assert UPLOAD_DIR  # keep the conventional import used

init_db()
client = TestClient(app)

CHROME = Path.home() / "pw-chrome" / "chrome-linux64" / "chrome"


def test_layout_has_viewport_and_pwa_tags():
    html = client.get("/").text
    assert 'name="viewport"' in html
    assert "width=device-width" in html
    assert 'rel="manifest"' in html
    assert 'name="theme-color"' in html
    assert "apple-touch-icon" in html
    assert 'class="tabbar"' in html


def test_manifest_json():
    r = client.get("/manifest.json")
    assert r.status_code == 200
    body = r.json()
    assert body["name"]
    assert body["short_name"]
    assert body["start_url"] == "/"
    assert body["display"] == "standalone"
    assert body["theme_color"]
    assert any(i["sizes"] == "512x512" for i in body["icons"])


def test_icons_served():
    for path in (
        "/static/img/icon.svg",
        "/static/img/icon-192.png",
        "/static/img/icon-512.png",
        "/static/img/apple-touch-icon.png",
    ):
        r = client.get(path)
        assert r.status_code == 200, path
        assert len(r.content) > 100, path


def test_camera_capture_attributes():
    for page in ("/identify", "/observations/new"):
        html = client.get(page).text
        assert 'accept="image/*"' in html, page
        assert 'capture="environment"' in html, page


def test_quick_log_structure():
    html = client.get("/observations/new").text
    # Big photo button comes before the species field; details collapse the rest.
    assert html.index("photo-btn") < html.index('id="species"')
    assert "<details" in html
    assert "btn-big" in html


def _serve(port: int):
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")


def test_no_horizontal_overflow_at_390px():
    """No page may scroll sideways at phone width (needs Chrome for Testing)."""
    if not CHROME.exists():
        import pytest

        pytest.skip("Chrome for Testing not available")
    import httpx
    from playwright.sync_api import sync_playwright

    port = 4123
    thread = threading.Thread(target=_serve, args=(port,), daemon=True)
    thread.start()
    for _ in range(50):
        try:
            httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=1.0)
            break
        except Exception:  # noqa: BLE001 — server still starting
            time.sleep(0.2)

    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(CHROME), args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 390, "height": 844})
        try:
            for path in (
                "/",
                "/observations",
                "/observations/new",
                "/identify",
                "/identify-audio",
                "/settings",
            ):
                page.goto(f"http://127.0.0.1:{port}{path}", wait_until="networkidle")
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth - document.documentElement.clientWidth"
                )
                assert overflow <= 1, f"{path} overflows horizontally by {overflow}px"
        finally:
            browser.close()
