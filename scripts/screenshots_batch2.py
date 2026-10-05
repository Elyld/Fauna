"""Capture batch-2 screenshots (1280x800 + one mobile) into docs/screenshots/.

Run while the app serves on :4001 with batch-2 demo data seeded.
Uses vanilla Chrome for Testing, no proxy for localhost. External assets
(Leaflet, map tiles, iNat thumbnails) are served via route interception.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

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
SHOTS = Path("/tmp/fauna-shots")

# A plain teddy-cream tile so maps render without external tile fetches.
TILE_PNG = SHOTS / "tile.png"
if not TILE_PNG.exists():
    import struct
    import zlib

    def _png(w, h, rgb):
        def chunk(t, d):
            c = t + d
            return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c))
        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
        return (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw))
            + chunk(b"IEND", b"")
        )

    TILE_PNG.write_bytes(_png(256, 256, (241, 230, 212)))
TILE_BYTES = TILE_PNG.read_bytes()
LEAFLET_JS = (SHOTS / "leaflet.js").read_bytes()
LEAFLET_CSS = (SHOTS / "leaflet.css").read_bytes()
LEAFLET_IMAGES = {
    f.name: f.read_bytes() for f in (SHOTS / "leaflet-images").glob("*.png")
}

# Generic iNat thumbnail cache: download on demand via proxy, serve from disk.
THUMB_DIR = SHOTS / "thumbs"
THUMB_DIR.mkdir(exist_ok=True)


def _thumb_bytes(url: str) -> bytes | None:
    import hashlib

    key = hashlib.sha256(url.encode()).hexdigest()[:16]
    for ext in (".jpg", ".png"):
        p = THUMB_DIR / f"{key}{ext}"
        if p.exists():
            return p.read_bytes()
    with _with_proxy():
        try:
            with httpx.Client(timeout=30.0) as c:
                img = c.get(url, timeout=30.0).content
            if img[:2] == b"\xff\xd8":
                (THUMB_DIR / f"{key}.jpg").write_bytes(img)
                return img
            if img[:8].startswith(b"\x89PNG"):
                (THUMB_DIR / f"{key}.png").write_bytes(img)
                return img
        except Exception as exc:  # noqa: BLE001
            print(f"thumb SKIP {url[:60]}: {exc}")
    return None


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        page = browser.new_page(viewport={"width": 1280, "height": 800})

        def _intercept(route):
            url = route.request.url
            if "127.0.0.1" in url or "localhost" in url:
                route.continue_()
            elif "unpkg.com/leaflet@1.9.4/dist/images/" in url:
                name = url.rsplit("/", 1)[-1]
                img = LEAFLET_IMAGES.get(name)
                if img:
                    route.fulfill(status=200, content_type="image/png", body=img)
                else:
                    route.abort()
            elif "unpkg.com/leaflet" in url:
                if url.endswith(".css"):
                    route.fulfill(status=200, content_type="text/css", body=LEAFLET_CSS)
                else:
                    route.fulfill(status=200, content_type="application/javascript", body=LEAFLET_JS)
            elif "tile.openstreetmap.org" in url:
                route.fulfill(status=200, content_type="image/png", body=TILE_BYTES)
            elif "static.inaturalist.org" in url or "inaturalist-open-data" in url:
                img = _thumb_bytes(url)
                if img:
                    route.fulfill(status=200, content_type="image/jpeg", body=img)
                else:
                    route.abort()
            else:
                route.abort()

        page.route("**/*", _intercept)

        page.goto(f"{BASE}/map", wait_until="networkidle")
        page.wait_for_timeout(1200)
        page.screenshot(path=str(OUT / "map.png"))
        print("map.png")

        page.goto(f"{BASE}/nearby", wait_until="networkidle")
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "nearby.png"))
        print("nearby.png")

        page.goto(f"{BASE}/wishlist", wait_until="networkidle")
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / "wishlist.png"))
        print("wishlist.png")

        # Gallery lightbox with multiple photos: click the tile that actually
        # has more than one photo (the multi-photo robin).
        page.goto(f"{BASE}/gallery", wait_until="networkidle")
        page.wait_for_timeout(600)
        idx = page.evaluate(
            "Array.from(document.querySelectorAll('.g-item'))"
            ".findIndex(b => JSON.parse(b.dataset.photos || '[]').length > 1)"
        )
        assert idx >= 0, "no multi-photo tile found"
        page.click(f".g-item >> nth={idx}")
        page.wait_for_timeout(800)
        count = page.text_content("#lightbox-count")
        print("lightbox count label:", repr(count))
        page.screenshot(path=str(OUT / "gallery-multi.png"))
        print("gallery-multi.png")

        # Mobile map.
        mob = browser.new_page(viewport={"width": 390, "height": 844})
        mob.route("**/*", _intercept)
        mob.goto(f"{BASE}/map", wait_until="networkidle")
        mob.wait_for_timeout(1200)
        mob.screenshot(path=str(OUT / "mobile-map.png"))
        print("mobile-map.png")

        browser.close()


if __name__ == "__main__":
    main()
