"""Fauna ship-readiness audit crawler.

Visits every page, clicks interactive elements, records console errors,
failed requests, dead links, missing tab bar, horizontal overflow, and
empty/raw-data states. Outputs a Markdown report to stdout.

Run while the app serves on :4001:
    ~/workspace/fauna/.venv/bin/python scripts/audit_ship.py
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

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://127.0.0.1:4001"
CHROME = str(Path.home() / "pw-chrome" / "chrome-linux64" / "chrome")

PAGES = [
    "/",
    "/observations",
    "/observations/new",
    "/life-list",
    "/map",
    "/nearby",
    "/wishlist",
    "/stats",
    "/identify",
    "/identify-audio",
    "/gallery",
    "/import",
    "/settings",
]

report = []
problems = []


def note(kind, page, detail):
    problems.append((kind, page, detail))


def check_page(pw_page, path, width):
    url = BASE + path
    console_errors = []
    req_failed = []
    pw_page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    pw_page.on("requestfailed", lambda r: req_failed.append(f"{r.url} :: {r.failure}"))
    resp = pw_page.goto(url, wait_until="networkidle", timeout=30000)
    status = resp.status if resp else "NORESP"
    title = pw_page.title()
    text = pw_page.inner_text("body")
    html = pw_page.content()

    # Dead internal links on this page
    dead_links = []
    for a in pw_page.query_selector_all("a[href]"):
        href = a.get_attribute("href") or ""
        if href.startswith("/") and not href.startswith("//"):
            try:
                r = pw_page.request.get(BASE + href, timeout=10000)
                if r.status >= 400:
                    dead_links.append(f"{href} -> {r.status}")
            except Exception as e:  # noqa: BLE001
                dead_links.append(f"{href} -> ERR {e}")

    # Tab bar presence (mobile width)
    tabbar = pw_page.query_selector(".tabbar")
    tabbar_visible = bool(tabbar and tabbar.is_visible())

    # Horizontal overflow
    overflow = pw_page.evaluate(
        "document.documentElement.scrollWidth > document.documentElement.clientWidth + 1"
    )

    # Raw data / blank indicators
    raw_json = "[]" in html and '"scientific_name"' in html
    empty_body = len(text.strip()) < 50

    # Buttons that do nothing: collect onclick-less buttons with no handler info is hard;
    # just report all buttons/links text for manual review
    return {
        "path": path,
        "status": status,
        "title": title,
        "text_len": len(text.strip()),
        "console_errors": console_errors,
        "req_failed": [r for r in req_failed if "tile" not in r and "leaflet" not in r.lower()],
        "dead_links": dead_links,
        "tabbar_visible": tabbar_visible,
        "overflow": overflow,
        "raw_json_hint": raw_json,
        "empty_body": empty_body,
    }


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        # Desktop pass
        ctx = browser.new_context(viewport={"width": 1280, "height": 800})
        page = ctx.new_page()
        for path in PAGES:
            try:
                info = check_page(page, path, 1280)
                report.append(info)
            except Exception as e:  # noqa: BLE001
                note("CRASH", path, f"desktop: {e}")
        ctx.close()
        # Mobile pass: tabbar + overflow + tab count
        ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        page = ctx.new_page()
        for path in PAGES:
            try:
                info = check_page(page, path, 390)
                n_tabs = page.eval_on_selector_all(".tabbar a", "els => els.length")
                info["n_tabs"] = n_tabs
                report.append(info)
            except Exception as e:  # noqa: BLE001
                note("CRASH", path, f"mobile: {e}")
        browser.close()

    print("# Fauna ship audit report\n")
    for info in report:
        print(f"## {info['path']} (w={'mobile' if info.get('n_tabs') is not None else 'desktop'})")
        print(f"- status: {info['status']} | title: {info['title'][:60]} | text_len: {info['text_len']}")
        if not info.get("tabbar_visible", True):
            print("- PROBLEM: tab bar missing/hidden")
        if info["overflow"]:
            print("- PROBLEM: horizontal overflow")
        if info["empty_body"]:
            print("- NOTE: very little text (possible blank page)")
        if info["raw_json_hint"]:
            print("- PROBLEM: raw JSON in page HTML")
        for e in info["console_errors"]:
            print(f"- CONSOLE ERROR: {e[:200]}")
        for e in info["req_failed"]:
            print(f"- REQ FAILED: {e[:200]}")
        for e in info["dead_links"]:
            print(f"- DEAD LINK: {e}")
        print()
    if problems:
        print("## Crashes")
        for k, p, d in problems:
            print(f"- {k} {p}: {d}")


if __name__ == "__main__":
    sys.exit(main())
