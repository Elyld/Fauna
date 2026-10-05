"""Capture mobile-settings.png + verify 6-tab bar at 390px."""
from __future__ import annotations

import os
import struct
import zlib
from pathlib import Path

for _var in ("NO_PROXY", "no_proxy"):
    _val = os.environ.get(_var)
    if _val and "[" in _val:
        os.environ[_val] = ",".join(p for p in _val.split(",") if "[" not in p)
for _var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_var, None)

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:4001"
CHROME = str(Path.home() / "pw-chrome" / "chrome-linux64" / "chrome")
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
SHOTS = Path("/tmp/fauna-shots")
SHOTS.mkdir(exist_ok=True)
if not (SHOTS / "tile.png").exists():
    def _png(w, h, rgb):
        def chunk(t, d):
            c = t + d
            return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c))
        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
        return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    (SHOTS / "tile.png").write_bytes(_png(256, 256, (241, 230, 212)))
TILE = (SHOTS / "tile.png").read_bytes()

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, device_scale_factor=2)
    page = ctx.new_page()

    def _route(route):
        url = route.request.url
        if url.startswith(BASE):
            route.continue_()
        elif url.endswith((".png", ".jpg", ".jpeg")) or "tile" in url:
            route.fulfill(body=TILE, content_type="image/png")
        else:
            route.abort()
    page.route("**/*", _route)

    page.goto(BASE + "/settings", wait_until="networkidle")
    page.wait_for_timeout(1200)
    tabs = page.eval_on_selector_all(".tabbar a", "els => els.map(e => e.textContent.trim())")
    print("tabs:", tabs)
    assert len(tabs) == 6, f"expected 6 tabs, got {len(tabs)}"
    assert any("Settings" in t for t in tabs), "no Settings tab!"
    # tap-target sizes
    boxes = page.eval_on_selector_all(".tabbar a", "els => els.map(e => { const r = e.getBoundingClientRect(); return Math.round(r.width) + 'x' + Math.round(r.height); })")
    print("tab sizes:", boxes)
    # check for horizontal overflow
    overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 1")
    print("horizontal overflow:", overflow)
    page.screenshot(path=str(OUT / "mobile-settings.png"), full_page=True)
    print("saved mobile-settings.png")

    # settings sections present?
    for needle in ["Photo ID", "Home location", "Backup", "OpenRouter"]:
        found = page.locator(f"text={needle}").count() > 0
        print(f"section '{needle}':", "yes" if found else "MISSING")
    browser.close()
print("OK")
