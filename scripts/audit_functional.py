"""Functional ship-readiness verification: cross-feature wiring via Playwright + API.

Run while the app serves on :4001. Uses httpx for API setup, Playwright
(Chrome for Testing, no proxy) for browser flows. Prints PASS/FAIL per check.
"""
from __future__ import annotations

import os
import sys
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
OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
SHOTS = Path("/tmp/fauna-shots")
SHOTS.mkdir(exist_ok=True)
if not (SHOTS / "tile.png").exists():
    import struct, zlib  # noqa: E402

    def _png(w, h, rgb):
        def chunk(t, d):
            c = t + d
            return struct.pack(">I", len(d)) + c + struct.pack(">I", zlib.crc32(c))
        ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
        raw = b"".join(b"\x00" + bytes(rgb) * w for _ in range(h))
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
                + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    (SHOTS / "tile.png").write_bytes(_png(256, 256, (241, 230, 212)))

results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


api = httpx.Client(base_url=BASE, timeout=20)

# ---------------------------------------------------------------- wishlist
w = api.post("/api/wishlist", json={"scientific_name": "Piranga olivacea", "common_name": "Scarlet Tanager", "notes": "bucket list"})
check("wishlist: add item", w.status_code == 200, w.text[:120])
wid = w.json().get("id") if w.status_code == 200 else None

dup = api.post("/api/wishlist", json={"scientific_name": "Piranga olivacea", "common_name": "Scarlet Tanager"})
check("wishlist: duplicate -> 409 not crash", dup.status_code == 409, f"got {dup.status_code}: {dup.text[:100]}")

# Seen badge: log the species, then check the wishlist page
o = api.post("/api/observations", json={"species_name": "Scarlet Tanager", "scientific_name": "Piranga olivacea", "count": 1})
obs_id = o.json().get("id") if o.status_code == 200 else None
check("setup: logged Scarlet Tanager", o.status_code == 200)

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 1280, "height": 800})
    page = ctx.new_page()
    # route interception for external junk (iNat thumbnails etc.)
    def _route(route):
        url = route.request.url
        if url.startswith(BASE) or url.startswith("http://127.0.0.1"):
            route.continue_()
        elif url.endswith(".png") or "tile" in url:
            route.fulfill(body=(SHOTS / "tile.png").read_bytes(), content_type="image/png")
        elif url.endswith(".jpg") or url.endswith(".jpeg"):
            route.fulfill(body=(SHOTS / "tile.png").read_bytes(), content_type="image/jpeg")
        else:
            route.abort()
    page.route("**/*", _route)

    page.goto(BASE + "/wishlist")
    seen = page.locator("text=Seen ✓").count() > 0
    check("wishlist: Seen ✓ badge after logging species", seen)
    rng = page.locator("a[href^='/species/']").count() > 0
    check("wishlist: range-map link present", rng)
    if wid:
        rm = page.locator(f"button[data-wishlist-remove='{wid}'], button[data-remove='{wid}']")
        n_rm = rm.count()
        check("wishlist: remove button present", n_rm > 0, f"found {n_rm}")

    # Nearby +Log it prefill
    page.goto(BASE + "/observations/new?species_name=Scarlet+Tanager&scientific_name=Piranga+olivacea")
    inp = page.locator("#species-name, input[name='species_name']").first
    sci = page.locator("#scientific, input[name='scientific_name']").first
    check("nearby log-it: species prefilled", inp.input_value() == "Scarlet Tanager", f"got '{inp.input_value()}'")
    check("nearby log-it: scientific prefilled", sci.input_value() == "Piranga olivacea", f"got '{sci.input_value()}'")

    # Edit observation: change notes
    if obs_id:
        page.goto(f"{BASE}/observations/{obs_id}/edit")
        page.locator("details summary").first.click()
        notes = page.locator("#notes, textarea[name='notes']").first
        notes.fill("Saw it at the feeder! Updated note.")
        page.locator("button[type='submit'], .btn[type='submit']").first.click()
        page.wait_for_timeout(1500)
        got = api.get(f"/api/observations/{obs_id}").json()
        check("edit: notes saved", "Updated note" in (got.get("notes") or ""), got.get("notes"))

    browser.close()

# cleanup wishlist + test obs
if wid:
    d = api.delete(f"/api/wishlist/{wid}")
    check("wishlist: remove works", d.status_code == 200)
if obs_id:
    api.delete(f"/api/observations/{obs_id}")

# ---------------------------------------------------------------- nearby no-home
saved = api.get("/api/settings").json()
api.put("/api/settings", json={"home_latitude": "", "home_longitude": "", "home_name": ""})
r = api.get("/nearby")
check("nearby: no home -> prompt to set location", "/settings" in r.text and "home" in r.text.lower())
api.put("/api/settings", json={"home_latitude": saved.get("home_latitude"), "home_longitude": saved.get("home_longitude"), "home_name": saved.get("home_name")})

# ---------------------------------------------------------------- ebird import
HEADER = ("Submission ID,Common Name,Scientific Name,Taxonomic Order,Count,"
          "State/Province,County,Location,Location ID,Latitude,Longitude,"
          "Date,Time,Protocol,Duration (Min),Observation Details,Checklist Comments")
CSV = HEADER + "\n" + "S77700001,American Robin,Turdus migratorius,1234,5,Kansas,Shawnee,Backyard,L123,39.05,-95.68,10-03-2026,07:30 AM,Stationary,30,Singing,,"
pv = api.post("/api/import/ebird/preview", files={"file": ("eb.csv", CSV, "text/csv")})
check("ebird: preview ok", pv.status_code == 200, pv.text[:100])
cf = api.post("/api/import/ebird/confirm", json={"rows": pv.json().get("new", [])}) if pv.status_code == 200 else None
check("ebird: confirm ok", cf is not None and cf.status_code == 200, (cf.text[:100] if cf else "no preview"))
ll = api.get("/life-list")
check("ebird: robin in life list", "American Robin" in ll.text)
st = api.get("/stats")
check("ebird: stats page ok", st.status_code == 200)
sq = api.get("/observations", params={"q": "robin"})
check("ebird: search finds robin", "American Robin" in sq.text)
mp = api.get("/map")
check("ebird: map renders with lat/lon pins", mp.status_code == 200 and "leaflet" in mp.text.lower())

# ---------------------------------------------------------------- photo ID w/o key
pid_r = api.post("/api/identify", files={"file": ("p.jpg", b"\xff\xd8\xff" + b"0" * 100, "image/jpeg")})
check("identify: no key -> friendly not_connected, still 200 by design", pid_r.status_code == 200 and pid_r.json().get("error") == "not_connected", f"got {pid_r.status_code}: {pid_r.text[:120]}")

# ---------------------------------------------------------------- backup contents
import io, zipfile  # noqa: E402
zb = api.get("/api/backup")
check("backup: downloads", zb.status_code == 200)
if zb.status_code == 200:
    zf = zipfile.ZipFile(io.BytesIO(zb.content))
    names = set(zf.namelist())
    for want in ("fauna.db", "photos/", "observations.json", "settings.json", "README.txt", "wishlist.json"):
        has = any(n == want or n.startswith(want) for n in names)
        check(f"backup: contains {want}", has)
    import sqlite3  # noqa: E402
    import tempfile  # noqa: E402
    tmpd = tempfile.mkdtemp()
    zf.extract("fauna.db", tmpd)
    con = sqlite3.connect(f"{tmpd}/fauna.db")
    tables = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    for t in ("observations", "observation_photos", "wishlist", "settings", "range_cache", "nearby_cache"):
        check(f"backup db: has table {t}", t in tables, str(sorted(tables)))

print(f"\n{sum(1 for _, ok, _ in results if ok)}/{len(results)} passed")
sys.exit(0 if all(ok for _, ok, _ in results) else 1)
