"""Verify offline outbox with MULTIPLE photos: queue offline, sync online."""
from __future__ import annotations

import os
import struct
import sys
import zlib
from pathlib import Path

for _var in ("NO_PROXY", "no_proxy"):
    _val = os.environ.get(_var)
    if _val and "[" in _val:
        os.environ[_var] = ",".join(p for p in _val.split(",") if "[" not in p)
for _var in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_var, None)

import httpx  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:4001"
CHROME = str(Path.home() / "pw-chrome" / "chrome-linux64" / "chrome")


def png(path, rgb):
    def chunk(t, d):
        c = t + d
        return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c))
    ihdr = struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes(rgb) * 64 for _ in range(64))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


p1 = Path("/tmp/off1.png"); p2 = Path("/tmp/off2.png")
png(p1, (200, 150, 120)); png(p2, (120, 170, 200))

api = httpx.Client(base_url=BASE, timeout=20)
before = api.get("/api/observations").json()
before_ids = {o["id"] for o in before["observations"]}

ok = True
with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
    page = ctx.new_page()
    page.goto(BASE + "/observations/new")
    page.wait_for_timeout(1000)
    # go offline
    ctx.set_offline(True)
    page.locator("#species").fill("Offline Testbird")
    page.evaluate("document.getElementById('scientific').value = 'Testus offlinus'")
    page.locator("#photo").set_input_files([str(p1), str(p2)])
    page.locator("button[type='submit']").first.click()
    page.wait_for_timeout(2500)
    queued = page.locator("text=will sync when").count() > 0
    print("offline: queued notice shown:", queued)
    ok &= queued
    banner = page.locator("#outbox-banner")
    banner_visible = banner.is_visible()
    print("offline: outbox banner visible:", banner_visible)
    ok &= banner_visible
    # back online, sync
    ctx.set_offline(False)
    page.wait_for_timeout(1000)
    page.locator("#outbox-sync").click()
    page.wait_for_timeout(4000)
    status = page.locator("#outbox-status").inner_text()
    print("sync status:", status)
    browser.close()

after = api.get("/api/observations").json()
new = [o for o in after["observations"] if o["id"] not in before_ids and o["species_name"] == "Offline Testbird"]
print("new observations:", len(new))
if new:
    oid = new[0]["id"]
    det = api.get(f"/api/observations/{oid}").json()
    n_photos = len(det.get("photos") or [])
    print("photos on synced observation:", n_photos)
    ok &= n_photos == 2
    api.delete(f"/api/observations/{oid}")
else:
    ok = False

print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
