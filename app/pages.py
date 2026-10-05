"""Server-rendered HTML pages for Fauna (teddy-bear theme).

The JSON API in app/main.py is untouched; these pages are a thin,
human-friendly layer on top of it.
"""
from __future__ import annotations

import html
import json
from datetime import datetime
from urllib.parse import quote, urlencode

from app.version import APP_NAME


def _esc(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso)
        return dt.strftime("%b %d, %Y")
    except ValueError:
        return iso


def _json_script(data) -> str:
    """JSON safe to embed in a <script type="application/json"> block.

    Script contents are raw text — HTML entities are NOT decoded — so _esc
    would corrupt any string values. Escaping "<" instead also neutralizes
    a "</script>" breakout.
    """
    return json.dumps(data).replace("<", "\\u003c")


def layout(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{_esc(title)} · {APP_NAME}</title>
<link rel="stylesheet" href="/static/css/theme.css">
<link rel="icon" href="/static/img/icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="/static/img/apple-touch-icon.png">
<link rel="manifest" href="/manifest.json">
<meta name="theme-color" content="#96637a">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="{APP_NAME}">
</head>
<body>
<header class="site-header">
  <a class="brand" href="/">🧸 {APP_NAME}</a>
  <nav>
    <a href="/">Home</a>
    <a href="/observations">Observations</a>
    <a href="/life-list">🦌 Life list</a>
    <a href="/map">🗺️ Map</a>
    <a href="/nearby">📍 Nearby</a>
    <a href="/wishlist">⭐ Wishlist</a>
    <a href="/stats">📊 Stats</a>
    <a href="/identify">🔍 Identify</a>
    <a href="/identify-audio">🎵 Sound ID</a>
    <a href="/gallery">🖼️ Gallery</a>
    <a href="/import">⬆️ Import</a>
    <a href="/observations/new">+ Log a sighting</a>
    <a href="/settings">⚙️ Settings</a>
  </nav>
</header>
<div id="offline-bar" class="offline-bar" hidden>📶 You're offline — you can still log sightings; they'll sync when you're back. Species search and ID features need a connection.</div>
<div id="outbox-banner" class="outbox-banner" hidden>📶 <span id="outbox-count">0</span> sighting(s) waiting to sync <button id="outbox-sync" class="btn btn-secondary" type="button">Sync now</button> <span id="outbox-status"></span></div>
<main class="wrap">
{body}
</main>
<nav class="tabbar" aria-label="Primary">
  <a href="/">🏠<span>Home</span></a>
  <a href="/observations">🐾<span>Sightings</span></a>
  <a href="/map">🗺️<span>Map</span></a>
  <a href="/identify">🔍<span>Identify</span></a>
  <a href="/identify-audio">🎵<span>Sound</span></a>
</nav>
<footer>{APP_NAME} · a wildlife observation journal</footer>
<script src="/static/js/outbox.js"></script>
<script>
(function () {{
  if ('serviceWorker' in navigator) {{
    navigator.serviceWorker.register('/sw.js').catch(function () {{}});
  }}
  var bar = document.getElementById('offline-bar');
  function updateOffline() {{
    bar.hidden = navigator.onLine;
  }}
  window.addEventListener('online', updateOffline);
  window.addEventListener('offline', updateOffline);
  updateOffline();

  // Outbox: queued sightings waiting for a connection.
  var banner = document.getElementById('outbox-banner');
  var countEl = document.getElementById('outbox-count');
  var statusEl = document.getElementById('outbox-status');
  var syncBtn = document.getElementById('outbox-sync');
  var dbPromise = null;
  function db() {{
    if (!dbPromise) dbPromise = window.FaunaOutbox.openDb().catch(function () {{ return null; }});
    return dbPromise;
  }}
  function refreshBanner() {{
    db().then(function (dbi) {{
      if (!dbi) return;
      return window.FaunaOutbox.countPending(dbi).then(function (n) {{
        banner.hidden = !n;
        countEl.textContent = n;
      }});
    }});
  }}
  function http() {{
    return {{
      postJson: function (url, obj) {{
        return fetch(url, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(obj) }})
          .then(function (r) {{ return r.json().then(function (b) {{ return {{ ok: r.ok, body: b }}; }}); }});
      }},
      postPhotos: function (obsId, photos) {{
        var fd = new FormData();
        photos.forEach(function (p) {{
          var parts = window.FaunaOutbox.dataUrlToParts(p.dataUrl);
          fd.append('files', window.FaunaOutbox.partsToBlob(parts), p.name);
        }});
        return fetch('/api/observations/' + obsId + '/photos', {{ method: 'POST', body: fd }})
          .then(function (r) {{ return r.json().then(function (b) {{ return {{ ok: r.ok, body: b }}; }}); }});
      }}
    }};
  }}
  function syncNow() {{
    syncBtn.disabled = true;
    statusEl.textContent = 'Syncing…';
    db().then(function (dbi) {{
      if (!dbi) throw new Error('no outbox');
      return window.FaunaOutbox.syncAll(dbi, http(), function (done, total) {{
        statusEl.textContent = 'Synced ' + done + ' of ' + total + '…';
      }});
    }}).then(function (res) {{
      statusEl.textContent = res.failed
        ? '✓ ' + res.synced + ' synced, ' + res.failed + ' still waiting.'
        : '✓ All synced!';
      refreshBanner();
    }}).catch(function () {{
      statusEl.textContent = "Couldn't sync — still offline?";
    }}).finally(function () {{
      syncBtn.disabled = false;
      setTimeout(function () {{ statusEl.textContent = ''; }}, 4000);
    }});
  }}
  syncBtn.addEventListener('click', syncNow);
  window.addEventListener('online', function () {{
    db().then(function (dbi) {{
      if (!dbi) return;
      return window.FaunaOutbox.countPending(dbi);
    }}).then(function (n) {{
      if (n) syncNow(); else refreshBanner();
    }});
  }});
  window.__faunaRefreshOutbox = refreshBanner;
  refreshBanner();
}})();
</script>
</body>
</html>"""


def card(obs: dict, show_edit: bool = False) -> str:
    photo = obs.get("photo_url")
    if photo:
        img = f'<img src="{_esc(photo)}" alt="{_esc(obs.get("species_name"))}">'
    else:
        img = '<div class="no-photo">🐾</div>'
    count = obs.get("count")
    badge = f'<span class="count-badge">×{count}</span>' if count and count > 1 else ""
    needs_id = '<span class="needs-id-badge">🧐 needs ID</span>' if obs.get("needs_id") else ""
    notes = obs.get("notes") or ""
    snippet = _esc(notes[:110] + ("…" if len(notes) > 110 else ""))
    edit = (
        f'<div class="card-actions"><a class="edit-link" href="/observations/{obs.get("id")}/edit">✏️ Edit</a></div>'
        if show_edit and obs.get("id")
        else ""
    )
    return f"""
<article class="card">
  {img}
  <div class="card-body">
    <h3>{_esc(obs.get("species_name") or "Unknown visitor")}{badge}{needs_id}</h3>
    <div class="sci">{_esc(obs.get("scientific_name") or "")}</div>
    <div class="meta">📅 {_esc(_fmt_date(obs.get("observed_at")))} · 📍 {_esc(obs.get("location_name") or "Somewhere lovely")}</div>
    {f'<div class="notes">{snippet}</div>' if snippet else ""}
    {edit}
  </div>
</article>"""


def home_page(total: int, species: int, recent: list[dict]) -> str:
    if recent:
        preview = '<div class="cards">\n' + "\n".join(card(o) for o in recent) + "\n</div>"
    else:
        preview = (
            '<div class="empty">No sightings yet — '
            '<a href="/observations/new">log your first one</a>! 🐿️</div>'
        )
    body = f"""
<section class="hero">
  <h1>🧸 {APP_NAME}</h1>
  <p class="tagline">Every squirrel, songbird, and bunny — noticed, named, and remembered.</p>
  <div class="stats">
    <div class="stat"><div class="num">{total}</div><div class="label">observations</div></div>
    <a class="stat stat-link" href="/life-list"><div class="num">{species}</div><div class="label">species 🦌</div></a>
  </div>
  <div class="cta-row">
    <a class="btn" href="/identify">🔍 What did I see?</a>
    <a class="btn" href="/identify-audio">🎵 What did I hear?</a>
    <a class="btn btn-secondary" href="/observations/new">+ Log a sighting</a>
    <a class="btn btn-secondary" href="/observations">Browse observations</a>
  </div>
</section>
<h2 class="section-title">Recent sightings</h2>
{preview}
"""
    return layout("Home", body)


def observations_page(
    observations: list[dict], q: str = "", needs_id_only: bool = False
) -> str:
    if observations:
        grid = '<div class="cards">\n' + "\n".join(
            card(o, show_edit=True) for o in observations
        ) + "\n</div>"
    elif q or needs_id_only:
        grid = (
            '<div class="empty">No sightings match that search. '
            '<a href="/observations">Clear the search</a> 🐾</div>'
        )
    else:
        grid = (
            '<div class="empty">Nothing here yet. '
            '<a href="/observations/new">Log your first sighting</a> 🐇</div>'
        )
    checked = "checked" if needs_id_only else ""
    body = f"""
<h2 class="section-title" style="margin-top:0">Observations</h2>
<form class="search-bar" method="get" action="/observations">
  <input type="search" name="q" value="{_esc(q)}" placeholder="Search species, places, notes…">
  <label class="search-check"><input type="checkbox" name="needs_id" value="true" {checked}> 🧐 Needs ID</label>
  <button class="btn btn-secondary" type="submit">Search</button>
  {f'<a href="/observations" class="clear-link">Clear</a>' if q or needs_id_only else ""}
</form>
<div class="cta-row" style="justify-content:flex-end">
  <a class="btn btn-secondary" href="/gallery">🖼️ Gallery</a>
  <a class="btn btn-secondary" href="/api/observations/export.csv">⬇️ Export CSV</a>
</div>
{grid}
"""
    return layout("Observations", body)


def life_list_page(rows: list[dict], sort: str = "recent") -> str:
    def sort_link(key: str, label: str) -> str:
        cls = "sort-active" if sort == key else ""
        return f'<a class="{cls}" href="/life-list?sort={key}">{label}</a>'

    if rows:
        cards = []
        for r in rows:
            if r["photo_url"]:
                img = f'<img src="{_esc(r["photo_url"])}" alt="{_esc(r["species_name"])}">'
            else:
                img = '<div class="no-photo">🦌</div>'
            ind = f' · {r["individuals"]} seen' if r["individuals"] > 1 else ""
            species_href = "/species/" + quote(r["scientific_name"] or r["species_name"] or "")
            cards.append(f"""
<article class="card life-card">
  {img}
  <div class="card-body">
    <h3><a class="species-link" href="{_esc(species_href)}">{_esc(r["species_name"])}</a></h3>
    <div class="sci">{_esc(r["scientific_name"] or "")}</div>
    <div class="meta">🐾 {r["sightings"]} sighting{"s" if r["sightings"] != 1 else ""}{ind}</div>
    <div class="meta">First: {_esc(_fmt_date(r["first_seen"]))} · Last: {_esc(_fmt_date(r["last_seen"]))}</div>
  </div>
</article>""")
        grid = '<div class="cards">\n' + "\n".join(cards) + "\n</div>"
    else:
        grid = (
            '<div class="empty">Your life list is empty — '
            '<a href="/observations/new">log your first sighting</a> and it\'ll appear here! 🦌</div>'
        )
    body = f"""
<h2 class="section-title" style="margin-top:0">🦌 Life list</h2>
<p class="hint" style="margin-top:0">Every species you've ever logged, in one brag-worthy place.</p>
<div class="sort-row">Sort: {sort_link("recent", "Most recent")} · {sort_link("most", "Most seen")} · {sort_link("alpha", "A–Z")}</div>
{grid}
"""
    return layout("Life list", body)


def _heat_class(count: int) -> str:
    if count < 0:
        return "pad"
    if count == 0:
        return "h0"
    if count <= 2:
        return "h1"
    if count <= 4:
        return "h2"
    return "h3"


def stats_page(data: dict) -> str:
    months = data["months"]
    peak = max((m["count"] for m in months), default=0)
    bars = []
    for m in months:
        pct = round(m["count"] / peak * 100) if peak else 0
        height = max(pct, 4) if m["count"] else 0
        bars.append(
            f'<div class="bar-col"><div class="bar" style="height:{height}%"></div>'
            f'<div class="bar-label">{m["label"]}</div>'
            f'<div class="bar-count">{m["count"]}</div></div>'
        )
    week_cols = []
    for week in data["weeks"]:
        cells = "".join(
            f'<div class="heat-cell {_heat_class(c["count"])}" title="{c["date"]}: '
            f'{c["count"] if c["count"] >= 0 else "—"}"></div>'
            for c in week
        )
        week_cols.append(f'<div class="heat-week">{cells}</div>')
    body = f"""
<h2 class="section-title" style="margin-top:0">📊 Stats</h2>
<h3 class="section-title">Sightings per month</h3>
<div class="bars">
{''.join(bars)}
</div>
<h3 class="section-title">Activity in {data["year"]}</h3>
<div class="heatmap-scroll"><div class="heatmap">
{''.join(week_cols)}
</div></div>
<div class="heat-legend"><span>Less</span>
<span class="heat-cell h0"></span><span class="heat-cell h1"></span><span class="heat-cell h2"></span><span class="heat-cell h3"></span>
<span>More</span></div>
"""
    return layout("Stats", body)


def identify_page() -> str:
    body = """
<h2 class="section-title" style="margin-top:0">🔍 What did I see?</h2>
<div id="id-offline-note" class="notice" hidden>📶 You're offline — photo ID needs a connection, but you can still <a href="/observations/new">log the sighting</a> and ID it later.</div>
<script>
(function () {
  var n = document.getElementById('id-offline-note');
  function upd() { n.hidden = navigator.onLine; }
  window.addEventListener('online', upd);
  window.addEventListener('offline', upd);
  upd();
})();
</script>
<div class="steps">
  <div class="step active" id="step-1">1 · Photo</div>
  <div class="step" id="step-2">2 · Confirm</div>
  <div class="step" id="step-3">3 · Details</div>
</div>

<div id="pane-photo">
  <div class="upload-zone" id="drop">
    <span class="big">📸</span>
    <strong>Drop a photo here, or tap to choose one</strong>
    <div class="hint" style="margin-top:0.4rem">A clear shot of the animal works best — even a phone photo through the window.</div>
    <input type="file" id="photo-input" accept="image/*" capture="environment" style="display:none">
  </div>
  <div id="preview-wrap" style="display:none; margin-top:1rem">
    <img id="preview" class="photo-preview" alt="Your photo">
    <div class="cta-row" style="justify-content:flex-start">
      <button class="btn" id="identify-btn">✨ Identify this photo</button>
      <button class="btn btn-secondary" id="change-btn" type="button">Choose a different photo</button>
    </div>
  </div>
</div>

<div id="pane-working" style="display:none">
  <div class="spinner"><span class="big">🔍</span>Taking a close look at your photo…</div>
</div>

<div id="pane-results" style="display:none">
  <div id="results-notice"></div>
  <h3 class="section-title" style="margin-top:0">We think this could be…</h3>
  <div class="suggestions" id="suggestions"></div>
  <div style="margin-top:1.25rem" class="cta-row">
    <a class="btn btn-secondary" id="manual-btn" href="#">None of these — I'll name it myself</a>
    <a href="/identify" style="align-self:center">↺ start over</a>
  </div>
</div>

<script>
(function () {
  var drop = document.getElementById('drop');
  var input = document.getElementById('photo-input');
  var previewWrap = document.getElementById('preview-wrap');
  var preview = document.getElementById('preview');
  var identifyBtn = document.getElementById('identify-btn');
  var changeBtn = document.getElementById('change-btn');
  var panes = {
    photo: document.getElementById('pane-photo'),
    working: document.getElementById('pane-working'),
    results: document.getElementById('pane-results')
  };
  var steps = [
    document.getElementById('step-1'),
    document.getElementById('step-2'),
    document.getElementById('step-3')
  ];
  var chosenFile = null;
  var pendingPhoto = null;

  function setStep(n) {
    steps.forEach(function (el, i) {
      el.classList.toggle('active', i === n - 1);
      el.classList.toggle('done', i < n - 1);
    });
  }
  function show(name) {
    Object.keys(panes).forEach(function (k) {
      panes[k].style.display = (k === name) ? '' : 'none';
    });
  }

  drop.addEventListener('click', function () { input.click(); });
  ['dragover', 'dragenter'].forEach(function (ev) {
    drop.addEventListener(ev, function (e) { e.preventDefault(); drop.style.background = 'var(--cream)'; });
  });
  drop.addEventListener('dragleave', function () { drop.style.background = ''; });
  drop.addEventListener('drop', function (e) {
    e.preventDefault(); drop.style.background = '';
    if (e.dataTransfer.files.length) pick(e.dataTransfer.files[0]);
  });
  input.addEventListener('change', function () { if (input.files.length) pick(input.files[0]); });
  changeBtn.addEventListener('click', function () {
    chosenFile = null; input.value = '';
    previewWrap.style.display = 'none'; drop.style.display = '';
  });

  function pick(file) {
    chosenFile = file;
    var url = URL.createObjectURL(file);
    preview.src = url;
    previewWrap.style.display = ''; drop.style.display = 'none';
  }

  identifyBtn.addEventListener('click', function () {
    if (!chosenFile) return;
    show('working'); setStep(1);
    var fd = new FormData();
    fd.append('file', chosenFile);
    fetch('/api/identify', { method: 'POST', body: fd })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error((res.body && res.body.detail) || 'Upload failed.');
        pendingPhoto = res.body.pending_photo;
        renderResults(res.body);
      })
      .catch(function (ex) {
        show('photo'); setStep(1);
        alert(ex.message || 'Something went wrong — please try again.');
      });
  });

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function renderResults(data) {
    show('results'); setStep(2);
    var notice = document.getElementById('results-notice');
    var box = document.getElementById('suggestions');
    notice.innerHTML = ''; box.innerHTML = '';

    var manualHref = '/observations/new?' + new URLSearchParams({
      photo: pendingPhoto || '', needs_id: '1'
    }).toString();
    document.getElementById('manual-btn').href = manualHref;

    if (data.error === 'not_connected' || data.error === 'token_expired') {
      notice.innerHTML = '<div class="notice">🔌 <strong>Photo ID isn\\'t connected yet.</strong> ' +
        'It needs a quick one-time setup: add an OpenRouter API key on the ' +
        '<a href="/settings">Settings</a> page. ' +
        'You can still log this sighting manually below — your photo is saved and ready.</div>';
    } else if (data.error === 'inat_unreachable' || data.error === 'vision_unreachable') {
      notice.innerHTML = '<div class="notice">📡 <strong>The identifier didn\\'t answer.</strong> ' +
        'Check your connection and try again, or log it manually below.</div>';
    } else if (data.error === 'vision_parse_failed') {
      notice.innerHTML = '<div class="notice">🧐 <strong>That answer came back garbled.</strong> ' +
        'Try the photo again, or log it manually below.</div>';
    } else if (data.error === 'no_animal_found') {
      notice.innerHTML = '<div class="notice">🐾 <strong>No animal spotted in that photo.</strong> ' +
        'A closer or clearer shot works best — or log it manually below.</div>';
    }

    (data.suggestions || []).forEach(function (s) {
      var score = s.combined_score != null ? s.combined_score : s.vision_score;
      var pct = score != null ? Math.round(score * 100) : null;
      var card = document.createElement('div');
      card.className = 'suggestion';
      card.innerHTML =
        (s.photo_url ? '<img src="' + esc(s.photo_url) + '" alt="">' : '<img alt="">') +
        '<div class="who">' +
          '<div class="common">' + esc(s.common_name || s.scientific_name || 'Unknown') + '</div>' +
          '<div class="sci">' + esc(s.scientific_name || '') + '</div>' +
          (pct != null
            ? '<div class="conf-bar"><div class="conf-fill" style="width:' + pct + '%"></div></div>' +
              '<div class="conf-label">' + pct + '% match</div>'
            : '') +
        '</div>';
      var btn = document.createElement('button');
      btn.className = 'btn';
      btn.type = 'button';
      btn.textContent = '✓ Yes, this one';
      btn.addEventListener('click', function () {
        var href = '/observations/new?' + new URLSearchParams({
          species_name: s.common_name || s.scientific_name || '',
          scientific_name: s.scientific_name || '',
          photo: pendingPhoto || ''
        }).toString();
        window.location = href;
      });
      card.appendChild(btn);
      box.appendChild(card);
    });
    setStep(3);
  }
})();
</script>
"""
    return layout("Identify", body)


def identify_audio_page() -> str:
    body = """
<h2 class="section-title" style="margin-top:0">🎵 What did I hear?</h2>
<div id="snd-offline-note" class="notice" hidden>📶 You're offline — sound ID needs a connection, but you can still <a href="/observations/new">log the sighting</a> and ID it later.</div>
<script>
(function () {
  var n = document.getElementById('snd-offline-note');
  function upd() { n.hidden = navigator.onLine; }
  window.addEventListener('online', upd);
  window.addEventListener('offline', upd);
  upd();
})();
</script>
<div class="steps">
  <div class="step active" id="astep-1">1 · Record</div>
  <div class="step" id="astep-2">2 · Confirm</div>
  <div class="step" id="astep-3">3 · Details</div>
</div>

<div id="apane-record">
  <div class="form-card" style="text-align:center">
    <span class="big" style="font-size:2.6rem">🎙️</span>
    <p style="color:var(--muted)">Record a few seconds of birdsong — a clear,
    close-up clip works best. Nothing is sent anywhere; it's analyzed right
    here on your own server.</p>
    <div class="cta-row">
      <button class="btn" id="rec-btn" type="button">● Start recording</button>
    </div>
    <div id="rec-status" style="margin-top:0.8rem; color:var(--muted)"></div>
    <div id="clip-wrap" style="display:none; margin-top:1rem">
      <audio id="clip-preview" controls style="width:100%"></audio>
      <div class="cta-row" style="margin-top:0.8rem">
        <button class="btn" id="aidentify-btn" type="button">✨ Identify this clip</button>
        <button class="btn btn-secondary" id="rerecord-btn" type="button">Record again</button>
      </div>
    </div>
    <div style="margin-top:1.2rem; color:var(--muted); font-size:0.9rem">
      or <a href="#" id="upload-link">upload an audio file instead</a>
      <input type="file" id="audio-input" accept="audio/*" style="display:none">
    </div>
  </div>
</div>

<div id="apane-working" style="display:none">
  <div class="spinner"><span class="big">🎵</span>Listening closely…</div>
</div>

<div id="apane-results" style="display:none">
  <div id="aresults-notice"></div>
  <h3 class="section-title" style="margin-top:0">We think this could be…</h3>
  <div class="suggestions" id="asuggestions"></div>
  <div style="margin-top:1.25rem" class="cta-row">
    <a class="btn btn-secondary" href="/observations/new?needs_id=1">None of these — I'll name it myself</a>
    <a href="/identify-audio" style="align-self:center">↺ start over</a>
  </div>
</div>

<script>
(function () {
  var recBtn = document.getElementById('rec-btn');
  var recStatus = document.getElementById('rec-status');
  var clipWrap = document.getElementById('clip-wrap');
  var clipPreview = document.getElementById('clip-preview');
  var identifyBtn = document.getElementById('aidentify-btn');
  var rerecordBtn = document.getElementById('rerecord-btn');
  var uploadLink = document.getElementById('upload-link');
  var audioInput = document.getElementById('audio-input');
  var panes = {
    record: document.getElementById('apane-record'),
    working: document.getElementById('apane-working'),
    results: document.getElementById('apane-results')
  };
  var steps = [
    document.getElementById('astep-1'),
    document.getElementById('astep-2'),
    document.getElementById('astep-3')
  ];
  var mediaRecorder = null, chunks = [], recTimer = null, recSecs = 0;
  var chosenFile = null;

  function setStep(n) {
    steps.forEach(function (el, i) {
      el.classList.toggle('active', i === n - 1);
      el.classList.toggle('done', i < n - 1);
    });
  }
  function show(name) {
    Object.keys(panes).forEach(function (k) {
      panes[k].style.display = (k === name) ? '' : 'none';
    });
  }
  function fmt(s) {
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }

  recBtn.addEventListener('click', function () {
    if (mediaRecorder && mediaRecorder.state === 'recording') {
      mediaRecorder.stop();
      return;
    }
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      recStatus.textContent = 'Recording isn\\'t supported in this browser — upload a file instead.';
      return;
    }
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (stream) {
      var mime = '';
      if (MediaRecorder.isTypeSupported('audio/webm;codecs=opus')) mime = 'audio/webm;codecs=opus';
      else if (MediaRecorder.isTypeSupported('audio/mp4')) mime = 'audio/mp4';
      chunks = [];
      mediaRecorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      mediaRecorder.ondataavailable = function (e) { if (e.data.size) chunks.push(e.data); };
      mediaRecorder.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        clearInterval(recTimer);
        var type = mediaRecorder.mimeType || 'audio/webm';
        var ext = type.indexOf('mp4') >= 0 ? 'mp4' : 'webm';
        chosenFile = new File(chunks, 'recording.' + ext, { type: type });
        clipPreview.src = URL.createObjectURL(chosenFile);
        clipWrap.style.display = '';
        recBtn.textContent = '● Start recording';
        recStatus.textContent = 'Recorded ' + fmt(recSecs) + ' — have a listen, then identify it.';
      };
      mediaRecorder.start();
      recSecs = 0;
      recStatus.textContent = '🔴 Recording… 0:00';
      recBtn.textContent = '⏹ Stop';
      recTimer = setInterval(function () {
        recSecs++;
        recStatus.textContent = '🔴 Recording… ' + fmt(recSecs);
        if (recSecs >= 60) mediaRecorder.stop();  // 60s cap
      }, 1000);
    }).catch(function () {
      recStatus.textContent = 'Couldn\\'t access the microphone — check permission, or upload a file.';
    });
  });

  rerecordBtn.addEventListener('click', function () {
    chosenFile = null; clipWrap.style.display = 'none'; recStatus.textContent = '';
  });
  uploadLink.addEventListener('click', function (e) { e.preventDefault(); audioInput.click(); });
  audioInput.addEventListener('change', function () {
    if (!audioInput.files.length) return;
    chosenFile = audioInput.files[0];
    clipPreview.src = URL.createObjectURL(chosenFile);
    clipWrap.style.display = '';
    recStatus.textContent = 'Loaded "' + chosenFile.name + '" — have a listen, then identify it.';
  });

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  identifyBtn.addEventListener('click', function () {
    if (!chosenFile) return;
    show('working'); setStep(1);
    var fd = new FormData();
    fd.append('file', chosenFile);
    fetch('/api/identify-audio', { method: 'POST', body: fd })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error((res.body && res.body.detail) || 'Upload failed.');
        renderResults(res.body);
      })
      .catch(function (ex) {
        show('record'); setStep(1);
        alert(ex.message || 'Something went wrong — please try again.');
      });
  });

  function renderResults(data) {
    show('results'); setStep(2);
    var notice = document.getElementById('aresults-notice');
    var box = document.getElementById('asuggestions');
    notice.innerHTML = ''; box.innerHTML = '';

    if (data.error === 'not_installed') {
      notice.innerHTML = '<div class="notice">🔌 <strong>Sound ID isn\\'t set up on this server yet.</strong> ' +
        'It needs the BirdNET engine (a one-time install). ' +
        'You can still log this sighting manually.</div>';
    } else if (data.error === 'analysis_failed') {
      notice.innerHTML = '<div class="notice">🎵 <strong>Couldn\\'t make sense of that clip.</strong> ' +
        'Try a clearer recording, closer to the bird.</div>';
    } else if (!(data.suggestions || []).length) {
      notice.innerHTML = '<div class="notice">🎵 <strong>No confident matches.</strong> ' +
        'The clip might be too quiet or too short — try again, or name it yourself below.</div>';
    }

    (data.suggestions || []).forEach(function (s) {
      var pct = s.combined_score != null ? Math.round(s.combined_score * 100) : null;
      var cardEl = document.createElement('div');
      cardEl.className = 'suggestion';
      cardEl.innerHTML =
        (s.photo_url ? '<img src="' + esc(s.photo_url) + '" alt="">' : '<div class="no-photo" style="width:84px;height:84px;border-radius:10px;flex-shrink:0">🐦</div>') +
        '<div class="who">' +
          '<div class="common">' + esc(s.common_name || s.scientific_name || 'Unknown') + '</div>' +
          '<div class="sci">' + esc(s.scientific_name || '') + '</div>' +
          (pct != null
            ? '<div class="conf-bar"><div class="conf-fill" style="width:' + pct + '%"></div></div>' +
              '<div class="conf-label">' + pct + '% match</div>'
            : '') +
        '</div>';
      var btn = document.createElement('button');
      btn.className = 'btn';
      btn.type = 'button';
      btn.textContent = '✓ Yes, this one';
      btn.addEventListener('click', function () {
        var href = '/observations/new?' + new URLSearchParams({
          species_name: s.common_name || s.scientific_name || '',
          scientific_name: s.scientific_name || '',
          notes: '🎵 Heard singing — identified with Sound ID.'
        }).toString();
        window.location = href;
      });
      cardEl.appendChild(btn);
      box.appendChild(cardEl);
    });
    setStep(3);
  }
})();
</script>
"""
    return layout("Sound ID", body)


def settings_page(current: dict | None = None) -> str:
    current = current or {}
    key_configured = current.get("openrouter_api_key_configured")
    vision_model = _esc(current.get("vision_model") or "")
    default_model = _esc(current.get("default_vision_model") or "")
    key_status = (
        '<div class="hint">✓ A key is saved. Entering a new one replaces it; '
        "leaving it blank keeps it.</div>"
        if key_configured
        else '<div class="hint">No key saved yet — photo ID will stay in manual mode.</div>'
    )
    home_lat = _esc(current.get("home_latitude") or "")
    home_lng = _esc(current.get("home_longitude") or "")
    home_name = _esc(current.get("home_name") or "")
    body = f"""
<h2 class="section-title" style="margin-top:0">⚙️ Settings</h2>
<div class="form-card">
  <h3 style="margin-top:0">Photo ID</h3>
  <p class="hint" style="margin-top:0">
    Photo ID asks a vision model (through OpenRouter) what animal is in a
    picture. Paste your OpenRouter API key once — it's stored on this server
    and never expires, so there's nothing to renew.
  </p>
  <form id="settings-form">
    <div class="field">
      <label for="or-key">OpenRouter API key</label>
      <input type="password" id="or-key" autocomplete="off"
             placeholder="sk-or-…">
      {key_status}
    </div>
    <div class="field">
      <label for="vision-model">Vision model</label>
      <input type="text" id="vision-model" value="{vision_model}">
      <div class="hint">Default: <code>{default_model}</code> (free). Free
      models can be slow or rate-limited — a cheap paid vision model costs a
      fraction of a cent per photo if one is ever needed.</div>
    </div>
    <div class="cta-row" style="justify-content:flex-start">
      <button class="btn" type="submit">Save settings</button>
    </div>
  </form>
  <div id="settings-msg" style="margin-top:0.75rem"></div>
</div>
<div class="form-card">
  <h3 style="margin-top:0">📍 Home location</h3>
  <p class="hint" style="margin-top:0">
    Used for <b>📍 Nearby</b> — "what's being seen around you right now".
    It's only ever used to look up nearby species; nothing leaves this server.
  </p>
  <form id="home-form">
    <div class="field">
      <label for="home-name">Place name</label>
      <input type="text" id="home-name" value="{home_name}" placeholder="Home">
    </div>
    <div class="form-row">
      <div class="field">
        <label for="home-lat">Latitude</label>
        <input type="text" id="home-lat" inputmode="decimal" value="{home_lat}" placeholder="39.05">
      </div>
      <div class="field">
        <label for="home-lng">Longitude</label>
        <input type="text" id="home-lng" inputmode="decimal" value="{home_lng}" placeholder="-95.68">
      </div>
    </div>
    <div class="cta-row" style="justify-content:flex-start">
      <button class="btn" type="submit">Save location</button>
      <button class="btn btn-secondary" type="button" id="use-my-location">📍 Use my location</button>
    </div>
  </form>
  <div id="home-msg" style="margin-top:0.75rem"></div>
</div>
<div class="form-card">
  <h3 style="margin-top:0">💾 Backup</h3>
  <p class="hint" style="margin-top:0">
    Download everything — every sighting, every photo, and the whole database —
    as one zip file. Keep it somewhere safe.
  </p>
  <div class="cta-row" style="justify-content:flex-start">
    <button class="btn" type="button" id="backup-btn">⬇️ Download backup</button>
  </div>
  <div id="backup-msg" style="margin-top:0.75rem"></div>
</div>
<script>
(function () {{
  var btn = document.getElementById('backup-btn');
  var msg = document.getElementById('backup-msg');
  btn.addEventListener('click', function () {{
    btn.disabled = true;
    btn.textContent = '⏳ Gathering everything…';
    msg.innerHTML = '';
    fetch('/api/backup')
      .then(function (r) {{
        if (!r.ok) throw new Error('backup failed');
        var disp = r.headers.get('Content-Disposition') || '';
        var m = /filename="?([^";]+)"?/.exec(disp);
        return r.blob().then(function (blob) {{
          return {{ blob: blob, name: m ? m[1] : 'fauna-backup.zip' }};
        }});
      }})
      .then(function (dl) {{
        var url = URL.createObjectURL(dl.blob);
        var a = document.createElement('a');
        a.href = url;
        a.download = dl.name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () {{ URL.revokeObjectURL(url); }}, 5000);
        msg.innerHTML = '<div class="notice">✓ Backup downloaded.</div>';
      }})
      .catch(function () {{
        msg.innerHTML = '<div class="notice">Couldn’t build the backup — please try again.</div>';
      }})
      .finally(function () {{
        btn.disabled = false;
        btn.textContent = '⬇️ Download backup';
      }});
  }});
}})();
</script>
<script>
(function () {{
  var form = document.getElementById('home-form');
  var msg = document.getElementById('home-msg');
  form.addEventListener('submit', function (e) {{
    e.preventDefault();
    var payload = {{
      home_name: document.getElementById('home-name').value,
      home_latitude: document.getElementById('home-lat').value,
      home_longitude: document.getElementById('home-lng').value
    }};
    fetch('/api/settings', {{
      method: 'PUT',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(payload)
    }})
      .then(function (r) {{
        if (!r.ok) throw new Error('Those coordinates don\u2019t look right.');
        return r.json();
      }})
      .then(function () {{
        msg.innerHTML = '<div class="notice">✓ Home location saved — <a href="/nearby">see what\u2019s nearby</a>.</div>';
      }})
      .catch(function (ex) {{
        msg.innerHTML = '<div class="notice">' + ex.message + '</div>';
      }});
  }});
  document.getElementById('use-my-location').addEventListener('click', function () {{
    if (!('geolocation' in navigator)) {{
      msg.innerHTML = '<div class="notice">This browser can\u2019t share its location — type it in instead.</div>';
      return;
    }}
    msg.innerHTML = '<div class="notice">Finding you…</div>';
    navigator.geolocation.getCurrentPosition(
      function (pos) {{
        document.getElementById('home-lat').value = pos.coords.latitude.toFixed(5);
        document.getElementById('home-lng').value = pos.coords.longitude.toFixed(5);
        if (!document.getElementById('home-name').value) {{
          document.getElementById('home-name').value = 'Home';
        }}
        msg.innerHTML = '<div class="notice">✓ Got it — hit <b>Save location</b>.</div>';
      }},
      function () {{
        msg.innerHTML = '<div class="notice">Couldn\u2019t get your location — type it in instead.</div>';
      }},
      {{ enableHighAccuracy: false, timeout: 10000, maximumAge: 600000 }}
    );
  }});
}})();
</script>
<script>
(function () {{
  var form = document.getElementById('settings-form');
  var msg = document.getElementById('settings-msg');
  form.addEventListener('submit', function (e) {{
    e.preventDefault();
    var key = document.getElementById('or-key').value;
    var model = document.getElementById('vision-model').value;
    var payload = {{ vision_model: model }};
    // Only send the key when she typed one — a blank field keeps what's saved.
    if (key) payload.openrouter_api_key = key;
    fetch('/api/settings', {{
      method: 'PUT',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(payload)
    }})
      .then(function (r) {{ return r.json(); }})
      .then(function () {{
        msg.innerHTML = '<div class="notice">✓ Saved.</div>';
        document.getElementById('or-key').value = '';
      }})
      .catch(function () {{
        msg.innerHTML = '<div class="notice">Couldn’t save — please try again.</div>';
      }});
  }});
}})();
</script>
"""
    return layout("Settings", body)


def _datetime_local_value(iso: str | None) -> str:
    """'2026-10-04T12:30:00' -> '2026-10-04T12:30' for datetime-local inputs."""
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%dT%H:%M")
    except ValueError:
        return ""


def _observation_form(prefill: dict, mode: str) -> str:
    """Shared sighting form. mode 'new' POSTs a create; 'edit' PUTs an update."""
    is_edit = mode == "edit"
    obs_id = prefill.get("obs_id")
    species = _esc(prefill.get("species_name") or "")
    scientific = _esc(prefill.get("scientific_name") or "")
    notes_prefill = _esc(prefill.get("notes") or "")
    location_prefill = _esc(prefill.get("location_name") or "")
    observed_prefill = _esc(prefill.get("observed_at") or "")
    count_prefill = prefill.get("count") or 1
    pending = prefill.get("pending_photo")
    existing_photos = prefill.get("existing_photos") or []
    needs_id_checked = "checked" if prefill.get("needs_id") else ""
    title = "Edit sighting" if is_edit else "Log a sighting"
    button = "Save changes" if is_edit else "Save sighting"

    camera_block = """
    <div class="field">
      <label class="photo-btn" for="photo">📸<span>Take a photo</span></label>
      <input type="file" id="photo" name="photo" accept="image/*" capture="environment" multiple style="display:none">
      <div class="photo-strip" id="photo-previews"></div>
      <div class="hint">Camera opens right away — or pick several from your gallery.</div>
    </div>"""
    if is_edit:
        chips = []
        for p in existing_photos:
            chips.append(
                f'<div class="photo-chip" data-photo-chip="{p["id"]}">'
                f'<img src="{_esc(p["photo_url"])}" alt="Sighting photo">'
                f'<button type="button" class="photo-del" data-del-photo="{p["id"]}" aria-label="Remove this photo">✕</button>'
                "</div>"
            )
        photo_block = f"""
    <div class="field">
      <label>Photos</label>
      <div class="photo-strip" id="existing-photos">
        {''.join(chips) if chips else '<span class="hint">No photos yet.</span>'}
      </div>
      <label class="photo-btn" for="photo" style="margin-top:0.6rem">📸<span>Add photos</span></label>
      <input type="file" id="photo" name="photo" accept="image/*" multiple style="display:none">
      <div class="photo-strip" id="photo-previews"></div>
    </div>"""
    elif pending:
        photo_block = f"""
    <div class="field">
      <label>Photo</label>
      <img src="{_esc(pending['url'])}" class="photo-preview" alt="Sighting photo">
      <input type="hidden" id="pending-photo" value="{_esc(pending['path'])}">
      <div class="hint">From your identification — it'll be saved with this sighting. You can add more below.</div>
      <label class="photo-btn" for="photo" style="margin-top:0.6rem">📸<span>Add more photos</span></label>
      <input type="file" id="photo" name="photo" accept="image/*" capture="environment" multiple style="display:none">
      <div class="photo-strip" id="photo-previews"></div>
    </div>"""
    else:
        photo_block = camera_block

    if is_edit:
        save_js = f"""
    function saveObservation() {{
      return fetch('/api/observations/{obs_id}', {{
        method: 'PUT',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(payload)
      }}).then(function (r) {{ return r.json().then(function (b) {{ return {{ ok: r.ok, body: b }}; }}); }});
    }}"""
    else:
        save_js = """
    function saveObservation() {
      return fetch('/api/observations', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      }).then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); });
    }"""

    body = f"""
<h2 class="section-title" style="margin-top:0">{title}</h2>
<div class="form-card">
  <div class="error" id="form-error"></div>
  <form id="obs-form">
    {photo_block}
    <div class="field">
      <label for="species">What did you see?</label>
      <input type="text" id="species" name="species_name" placeholder="Start typing — e.g. squirrel" autocomplete="off" value="{species}">
      <input type="hidden" id="scientific" name="scientific_name" value="{scientific}">
      <div class="autocomplete" id="ac-list"></div>
      <div class="hint">Suggestions come from the iNaturalist wildlife database.</div>
    </div>
    <details class="details-card">
      <summary>More details</summary>
      <div class="details-body">
        <label class="checkbox-row">
          <input type="checkbox" id="needs-id" {needs_id_checked}>
          <span class="cb-text"><strong>I'm not sure what this is.</strong><br>Flag it so we remember the ID still needs confirming.</span>
        </label>
        <div class="form-row">
          <div class="field">
            <label for="count">How many?</label>
            <input type="number" id="count" name="count" min="1" value="{count_prefill}">
          </div>
          <div class="field">
            <label for="observed_at">When?</label>
            <input type="datetime-local" id="observed_at" name="observed_at" value="{observed_prefill}">
          </div>
        </div>
        <div class="field">
          <label for="location">Where?</label>
          <input type="text" id="location" name="location_name" placeholder="Backyard oak, riverside trail…" value="{location_prefill}">
        </div>
        <div class="field">
          <label for="notes">Notes</label>
          <textarea id="notes" name="notes" placeholder="What was it doing? Anything charming?">{notes_prefill}</textarea>
        </div>
      </div>
    </details>
    <button class="btn btn-big" type="submit">{button}</button>
  </form>
</div>
<script>
(function () {{
  var input = document.getElementById('species');
  var sci = document.getElementById('scientific');
  var list = document.getElementById('ac-list');
  var timer = null;

  function close() {{ list.classList.remove('open'); list.innerHTML = ''; }}

  input.addEventListener('input', function () {{
    sci.value = '';
    clearTimeout(timer);
    var q = input.value.trim();
    if (q.length < 2) {{ close(); return; }}
    timer = setTimeout(function () {{
      fetch('/api/species/search?q=' + encodeURIComponent(q) + '&per_page=6')
        .then(function (r) {{ return r.json(); }})
        .then(function (data) {{
          var results = (data && data.results) || [];
          if (!results.length) {{ close(); return; }}
          list.innerHTML = '';
          results.forEach(function (t) {{
            var item = document.createElement('div');
            item.className = 'ac-item';
            var img = t.photo_url
              ? '<img src="' + t.photo_url.replace(/"/g, '') + '" alt="">'
              : '<img alt="">';
            item.innerHTML = img +
              '<div class="names"><div class="common"></div><div class="sci"></div></div>';
            item.querySelector('.common').textContent = t.common_name || t.scientific_name || 'Unknown';
            item.querySelector('.sci').textContent = t.scientific_name || '';
            item.addEventListener('mousedown', function (e) {{
              e.preventDefault();
              input.value = t.common_name || t.scientific_name || '';
              sci.value = t.scientific_name || '';
              close();
            }});
            list.appendChild(item);
          }});
          list.classList.add('open');
        }})
        .catch(function () {{ close(); }});
    }}, 250);
  }});

  document.addEventListener('click', function (e) {{
    if (!list.contains(e.target) && e.target !== input) close();
  }});

  // Photo previews for the camera button (all chosen files).
  var photoInput = document.getElementById('photo');
  var previews = document.getElementById('photo-previews');
  if (photoInput && previews) {{
    photoInput.addEventListener('change', function () {{
      previews.innerHTML = '';
      Array.prototype.forEach.call(photoInput.files, function (f) {{
        var img = document.createElement('img');
        img.className = 'photo-thumb';
        img.alt = 'Photo preview';
        img.src = URL.createObjectURL(f);
        previews.appendChild(img);
      }});
    }});
  }}

  // Edit mode: remove an existing photo without leaving the page.
  var existingStrip = document.getElementById('existing-photos');
  if (existingStrip) {{
    existingStrip.addEventListener('click', function (e) {{
      var btn = e.target.closest ? e.target.closest('[data-del-photo]') : null;
      if (!btn) return;
      var pid = btn.getAttribute('data-del-photo');
      btn.disabled = true;
      fetch('/api/observations/{obs_id}/photos/' + pid, {{ method: 'DELETE' }})
        .then(function (r) {{
          if (!r.ok) throw new Error('remove failed');
          var chip = existingStrip.querySelector('[data-photo-chip="' + pid + '"]');
          if (chip) chip.remove();
          if (!existingStrip.querySelector('[data-photo-chip]')) {{
            existingStrip.innerHTML = '<span class="hint">No photos yet.</span>';
          }}
        }})
        .catch(function () {{ btn.disabled = false; }});
    }});
  }}

  function readFileAsDataUrl(file) {{
    return new Promise(function (resolve, reject) {{
      var r = new FileReader();
      r.onload = function () {{ resolve({{ name: file.name, dataUrl: r.result }}); }};
      r.onerror = function () {{ reject(r.error); }};
      r.readAsDataURL(file);
    }});
  }}

  document.getElementById('obs-form').addEventListener('submit', function (e) {{
    e.preventDefault();
    var err = document.getElementById('form-error');
    err.classList.remove('show');
    var observed = document.getElementById('observed_at').value;
    var pendingPhotoEl = document.getElementById('pending-photo');
    var payload = {{
      species_name: input.value.trim() || null,
      scientific_name: sci.value || null,
      count: parseInt(document.getElementById('count').value, 10) || 1,
      observed_at: observed ? new Date(observed).toISOString() : null,
      location_name: document.getElementById('location').value.trim() || null,
      notes: document.getElementById('notes').value.trim() || null,
      needs_id: document.getElementById('needs-id').checked,
      photo_path: pendingPhotoEl ? pendingPhotoEl.value : null
    }};
    var files = (photoInput && photoInput.files) ? Array.prototype.slice.call(photoInput.files) : [];
    {save_js}
    function uploadAll(obsId) {{
      if (!files.length) return Promise.resolve();
      var fd = new FormData();
      files.forEach(function (f) {{ fd.append('files', f, f.name); }});
      return fetch('/api/observations/' + obsId + '/photos', {{ method: 'POST', body: fd }})
        .then(function (r) {{
          if (!r.ok) throw new Error('Photos could not be saved.');
        }});
    }}
    // Offline: queue the sighting (fields + photos) in the outbox; it syncs
    // through the normal API when the connection comes back.
    if (!navigator.onLine && window.FaunaOutbox) {{
      Promise.all(files.map(readFileAsDataUrl)).then(function (photos) {{
        return window.FaunaOutbox.openDb().then(function (dbi) {{
          return window.FaunaOutbox.savePending(dbi, {{ payload: payload, photos: photos }});
        }});
      }}).then(function () {{
        if (window.__faunaRefreshOutbox) window.__faunaRefreshOutbox();
        err.textContent = '';
        err.classList.remove('show');
        var done = document.createElement('div');
        done.className = 'notice';
        done.textContent = '📶 Saved — it will sync when you\u2019re back online.';
        document.getElementById('obs-form').prepend(done);
        setTimeout(function () {{ window.location = '/observations'; }}, 1500);
      }}).catch(function () {{
        err.textContent = 'Could not save offline — please try again.';
        err.classList.add('show');
      }});
      return;
    }}
    // Online: save the record, then upload any picked photos.
    // A pending photo from Identify rides along in the payload instead.
    saveObservation()
      .then(function (res) {{
        if (!res.ok) throw new Error('Could not save the sighting.');
        return uploadAll(res.body.id);
      }})
      .then(function () {{ window.location = '/observations'; }})
      .catch(function (ex) {{
        err.textContent = ex.message || 'Something went wrong.';
        err.classList.add('show');
      }});
  }});
}})();
</script>
"""
    return layout(title, body)


def new_observation_page(prefill: dict | None = None) -> str:
    return _observation_form(prefill or {}, mode="new")


def edit_observation_page(obs: dict) -> str:
    """Prefilled form for editing an existing sighting."""
    return _observation_form(
        {
            "obs_id": obs["id"],
            "species_name": obs.get("species_name") or "",
            "scientific_name": obs.get("scientific_name") or "",
            "count": obs.get("count") or 1,
            "observed_at": _datetime_local_value(obs.get("observed_at")),
            "location_name": obs.get("location_name") or "",
            "notes": obs.get("notes") or "",
            "needs_id": obs.get("needs_id"),
            "existing_photos": obs.get("photos") or [],
        },
        mode="edit",
    )


def import_page() -> str:
    body = """
<h2 class="section-title" style="margin-top:0">⬆️ Bring your eBird history</h2>
<div class="form-card">
  <p>On eBird.org go to <b>My eBird → Download My Data</b>, then upload the CSV
  here. I'll show you exactly what I found <i>before</i> anything gets saved —
  and sightings you've already imported are skipped automatically.</p>
  <div class="field">
    <label for="csv">eBird CSV file</label>
    <input type="file" id="csv" accept=".csv,text/csv">
  </div>
  <div class="error" id="import-error"></div>
  <button class="btn-big" id="preview-btn" type="button">Preview import</button>
</div>
<div id="preview-result"></div>
<script>
let pendingRows = [];
function _esc(s){return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
document.getElementById('preview-btn').addEventListener('click', async () => {
  const err = document.getElementById('import-error');
  err.textContent = '';
  const f = document.getElementById('csv').files[0];
  if (!f) { err.textContent = 'Pick a CSV file first.'; return; }
  const fd = new FormData(); fd.append('file', f);
  const btn = document.getElementById('preview-btn');
  btn.disabled = true; btn.textContent = 'Reading…';
  try {
    const r = await fetch('/api/import/ebird/preview', {method: 'POST', body: fd});
    if (!r.ok) { const j = await r.json().catch(() => ({})); throw new Error(j.detail || 'preview failed'); }
    const d = await r.json();
    pendingRows = d.new;
    renderPreview(d);
  } catch (e) { err.textContent = e.message; }
  finally { btn.disabled = false; btn.textContent = 'Preview import'; }
});
function rowHtml(r) {
  const d = r.observed_at ? r.observed_at.slice(0, 10) : '—';
  return `<tr><td>${_esc(r.species_name || '')}<div class="sci">${_esc(r.scientific_name || '')}</div></td><td>${_esc(d)}</td><td>${_esc(r.location_name || '—')}</td></tr>`;
}
function renderPreview(d) {
  const box = document.getElementById('preview-result');
  const sample = d.new.slice(0, 5).map(rowHtml).join('');
  const skips = d.skipped.slice(0, 8).map(s => `<li>Row ${s.line}: ${_esc(s.reason)}</li>`).join('');
  box.innerHTML = `
  <div class="form-card" style="margin-top:1rem">
    <h3>Ready when you are</h3>
    <p class="stat-line"><b>${d.new_count}</b> new sightings &middot; <b>${d.already_count}</b> already in your journal &middot; <b>${d.skipped.length}</b> skipped</p>
    ${sample ? `<table class="preview-table"><thead><tr><th>Species</th><th>Date</th><th>Where</th></tr></thead><tbody>${sample}</tbody></table>` : '<p>No new sightings in this file.</p>'}
    ${skips ? `<details class="details-card"><summary>Skipped rows (${d.skipped.length})</summary><ul>${skips}</ul></details>` : ''}
    ${d.new_count ? `<button class="btn-big" id="confirm-btn" type="button">Import ${d.new_count} sightings</button>` : ''}
    <div class="error" id="confirm-error"></div>
  </div>`;
  const cb = document.getElementById('confirm-btn');
  if (cb) cb.addEventListener('click', confirmImport);
}
async function confirmImport() {
  const ce = document.getElementById('confirm-error'); ce.textContent = '';
  const btn = document.getElementById('confirm-btn');
  btn.disabled = true; btn.textContent = 'Importing…';
  try {
    const r = await fetch('/api/import/ebird/confirm', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({rows: pendingRows})});
    if (!r.ok) throw new Error('import failed');
    const d = await r.json();
    document.getElementById('preview-result').innerHTML = `
    <div class="form-card" style="margin-top:1rem">
      <h3>🎉 All set!</h3>
      <p><b>${d.imported}</b> sightings added to your journal${d.skipped_dupes ? ` &middot; ${d.skipped_dupes} already imported` : ''}.</p>
      <p><a href="/observations">Browse your sightings</a> &middot; <a href="/life-list">See your life list</a></p>
    </div>`;
  } catch (e) { ce.textContent = e.message; btn.disabled = false; btn.textContent = 'Import sightings'; }
}
</script>
"""
    return layout("Import from eBird", body)


LEAFLET_CSS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
LEAFLET_JS = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"


def species_page(
    taxon: dict | None,
    range_data: dict,
    own_points: list[dict],
    sightings: list[dict],
    display_name: str,
) -> str:
    """Per-species detail: taxon card, range map, and her own sightings."""
    common = (taxon or {}).get("common_name") or display_name
    sci = (taxon or {}).get("scientific_name") or display_name
    photo = (taxon or {}).get("photo_url")
    wiki = (taxon or {}).get("wikipedia_url")
    if photo:
        img = f'<img src="{_esc(photo)}" alt="{_esc(common)}" class="species-photo">'
    else:
        img = '<div class="no-photo species-photo">🦌</div>'

    points = range_data.get("points") or []
    err = range_data.get("error")
    if err == "no_taxon_match":
        map_note = "We couldn't find this species in the wildlife database, so there's no range map for it."
    elif err == "no_observations":
        map_note = "The wildlife database has no mapped observations for this species yet."
    elif err in ("lookup_failed", "fetch_failed"):
        map_note = "The range map couldn't load right now — the wildlife database isn't answering. Try again later."
    elif err == "no_name":
        map_note = ""
    else:
        map_note = ""
    n_inat = len(points)
    n_mine = len(own_points)
    if not map_note:
        map_note = (
            f"{n_inat} research-grade observations from the iNaturalist community"
            + (f" · {n_mine} of your sightings pinned in brown" if n_mine else "")
            + "."
        )

    points_json = _json_script([[p[0], p[1]] for p in points])
    own_json = _json_script(own_points)

    if sightings:
        mine = '<div class="cards">\n' + "\n".join(
            card(o, show_edit=True) for o in sightings
        ) + "\n</div>"
    else:
        mine = (
            '<div class="empty">No sightings of this species in your journal yet. '
            '<a href="/observations/new">Log one</a> 🐾</div>'
        )

    body = f"""
<div class="species-head">
  {img}
  <div>
    <h2 class="section-title" style="margin:0">{_esc(common)}</h2>
    <div class="sci">{_esc(sci)}</div>
    {f'<div class="meta"><a href="{_esc(wiki)}" target="_blank" rel="noopener">📖 Wikipedia</a></div>' if wiki else ""}
  </div>
</div>

<h3 class="section-title">🗺️ Where they're normally seen</h3>
<p class="hint">{_esc(map_note)}</p>
<link rel="stylesheet" href="{LEAFLET_CSS}">
<div id="range-map" class="range-map" role="img" aria-label="Range map"></div>
<div id="range-map-fallback" class="map-fallback" hidden>
  🗺️ The interactive map couldn't load (it needs the map library from the internet),
  but the rest of this page is fine.
</div>
<script type="application/json" id="range-points">{points_json}</script>
<script type="application/json" id="own-points">{own_json}</script>
<script src="{LEAFLET_JS}"></script>
<script>
(function () {{
  var fallback = document.getElementById('range-map-fallback');
  var el = document.getElementById('range-map');
  if (typeof L === 'undefined') {{
    el.style.display = 'none';
    fallback.hidden = false;
    return;
  }}
  var map = L.map('range-map', {{ scrollWheelZoom: false }}).setView([39.5, -98.35], 3);
  L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }}).addTo(map);
  var pts = JSON.parse(document.getElementById('range-points').textContent);
  var own = JSON.parse(document.getElementById('own-points').textContent);
  var bounds = [];
  pts.forEach(function (p) {{
    L.circleMarker([p[0], p[1]], {{
      radius: 3, color: '#b48396', fillColor: '#c99bac', fillOpacity: 0.7, weight: 1
    }}).addTo(map);
    bounds.push([p[0], p[1]]);
  }});
  own.forEach(function (p) {{
    L.marker([p.lat, p.lng]).addTo(map).bindPopup(p.label || 'Your sighting');
    bounds.push([p.lat, p.lng]);
  }});
  if (bounds.length) map.fitBounds(bounds, {{ padding: [24, 24] }});
  map.on('focus', function () {{ map.scrollWheelZoom.enable(); }});
  map.on('blur', function () {{ map.scrollWheelZoom.disable(); }});
}})();
</script>

<h3 class="section-title">🐾 Your sightings</h3>
{mine}
"""
    return layout(f"{common}", body)


def gallery_page(
    items: list[dict],
    species_options: list[str],
    selected_species: str = "",
    q: str = "",
) -> str:
    """Photo grid with lightbox; sightings without photos are simply absent."""
    opts = ['<option value="">All species</option>'] + [
        f'<option value="{_esc(s)}"{" selected" if s == selected_species else ""}>{_esc(s)}</option>'
        for s in species_options
    ]
    if items:
        tiles = []
        for o in items:
            caption = _esc(o.get("species_name") or "Unknown visitor")
            sub = _esc(
                " · ".join(
                    x
                    for x in [
                        _fmt_date(o.get("observed_at")),
                        o.get("location_name") or "",
                    ]
                    if x and x != "—"
                )
            )
            photos = [p.get("photo_url") for p in (o.get("photos") or []) if p.get("photo_url")]
            if not photos and o.get("photo_url"):
                photos = [o["photo_url"]]
            n_photos = f" · {len(photos)} photos" if len(photos) > 1 else ""
            view_href = "/observations?" + urlencode(
                {"q": o.get("species_name") or ""}
            ) if o.get("species_name") else "/observations"
            tiles.append(f"""
<button class="g-item" data-full="{_esc(o.get("photo_url"))}"
        data-caption="{caption}" data-sub="{sub}{_esc(n_photos)}" data-view="{_esc(view_href)}"
        data-photos="{_esc(json.dumps(photos))}">
  <img src="{_esc(o.get("photo_url"))}" alt="{caption}" loading="lazy">
  <span class="g-cap">{caption}</span>
</button>""")
        grid = '<div class="gallery-grid">\n' + "\n".join(tiles) + "\n</div>"
    else:
        grid = (
            '<div class="empty">No photos match. '
            '<a href="/gallery">Clear the filters</a> 📸</div>'
            if (selected_species or q)
            else '<div class="empty">No photos yet — <a href="/observations/new">log a sighting with a photo</a> 📸</div>'
        )
    body = f"""
<h2 class="section-title" style="margin-top:0">🖼️ Gallery</h2>
<form class="search-bar" method="get" action="/gallery">
  <select name="species" aria-label="Filter by species">
    {"".join(opts)}
  </select>
  <input type="search" name="q" value="{_esc(q)}" placeholder="Search photos…">
  <button class="btn btn-secondary" type="submit">Filter</button>
  {f'<a href="/gallery" class="clear-link">Clear</a>' if (selected_species or q) else ""}
</form>
{grid}
<div class="lightbox" id="lightbox" hidden>
  <button class="lightbox-close" id="lightbox-close" aria-label="Close">✕</button>
  <button class="lightbox-nav lightbox-prev" id="lightbox-prev" aria-label="Previous photo">‹</button>
  <img id="lightbox-img" alt="">
  <button class="lightbox-nav lightbox-next" id="lightbox-next" aria-label="Next photo">›</button>
  <div class="lightbox-cap"><div id="lightbox-caption"></div><div id="lightbox-sub" class="sci"></div><div id="lightbox-count" class="sci"></div><a id="lightbox-view" href="/observations">View sighting →</a></div>
</div>
<script>
(function () {{
  var box = document.getElementById('lightbox');
  var img = document.getElementById('lightbox-img');
  var view = document.getElementById('lightbox-view');
  var countEl = document.getElementById('lightbox-count');
  var photos = [];
  var idx = 0;
  function show(i) {{
    if (!photos.length) return;
    idx = (i + photos.length) % photos.length;
    img.src = photos[idx];
    countEl.textContent = photos.length > 1 ? (idx + 1) + ' of ' + photos.length : '';
    var showNav = photos.length > 1;
    document.getElementById('lightbox-prev').style.display = showNav ? '' : 'none';
    document.getElementById('lightbox-next').style.display = showNav ? '' : 'none';
  }}
  document.querySelectorAll('.g-item').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      try {{
        photos = JSON.parse(btn.dataset.photos || '[]');
      }} catch (e) {{ photos = []; }}
      if (!photos.length && btn.dataset.full) photos = [btn.dataset.full];
      img.alt = btn.dataset.caption;
      document.getElementById('lightbox-caption').textContent = btn.dataset.caption;
      document.getElementById('lightbox-sub').textContent = btn.dataset.sub;
      view.href = btn.dataset.view;
      box.hidden = false;
      document.body.style.overflow = 'hidden';
      show(0);
    }});
  }});
  document.getElementById('lightbox-prev').addEventListener('click', function (e) {{ e.stopPropagation(); show(idx - 1); }});
  document.getElementById('lightbox-next').addEventListener('click', function (e) {{ e.stopPropagation(); show(idx + 1); }});
  function close() {{ box.hidden = true; document.body.style.overflow = ''; }}
  document.getElementById('lightbox-close').addEventListener('click', close);
  box.addEventListener('click', function (e) {{ if (e.target === box) close(); }});
  document.addEventListener('keydown', function (e) {{
    if (box.hidden) return;
    if (e.key === 'Escape') close();
    if (e.key === 'ArrowLeft') show(idx - 1);
    if (e.key === 'ArrowRight') show(idx + 1);
  }});
}})();
</script>
"""
    return layout("Gallery", body)


def map_page(pins: list[dict], species_options: list[str], selected_species: str = "") -> str:
    """🗺️ Map of HER sightings that have a location."""
    opts = ['<option value="">All species</option>'] + [
        f'<option value="{_esc(s)}"{" selected" if s == selected_species else ""}>{_esc(s)}</option>'
        for s in species_options
    ]
    pins_json = _json_script(pins)
    if pins:
        map_html = f"""
<link rel="stylesheet" href="{LEAFLET_CSS}">
<div id="sightings-map" class="range-map" role="img" aria-label="Sightings map"></div>
<div id="range-map-fallback" class="map-fallback" hidden>
  🗺️ The interactive map couldn't load (it needs the map library from the internet),
  but your sightings are listed below.
</div>
<script type="application/json" id="map-pins">{pins_json}</script>
<script src="{LEAFLET_JS}"></script>
<script>
(function () {{
  var fallback = document.getElementById('range-map-fallback');
  var el = document.getElementById('sightings-map');
  if (typeof L === 'undefined') {{
    el.style.display = 'none';
    fallback.hidden = false;
    return;
  }}
  var pins = JSON.parse(document.getElementById('map-pins').textContent);
  var map = L.map('sightings-map', {{ scrollWheelZoom: false }});
  L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
  }}).addTo(map);
  var bounds = [];
  pins.forEach(function (p) {{
    var html = '';
    if (p.thumb) html += '<img src="' + p.thumb.replace(/"/g, '') + '" class="map-thumb" alt="">';
    html += '<div class="map-pin-title">' + p.species.replace(/</g, '&lt;') + '</div>';
    if (p.date) html += '<div class="sci">' + p.date.replace(/</g, '&lt;') + '</div>';
    html += '<a href="' + p.href.replace(/"/g, '') + '">View sighting →</a>';
    L.marker([p.lat, p.lng]).addTo(map).bindPopup(html);
    bounds.push([p.lat, p.lng]);
  }});
  if (bounds.length === 1) map.setView(bounds[0], 12);
  else if (bounds.length) map.fitBounds(bounds, {{ padding: [32, 32] }});
  else map.setView([39.5, -98.35], 3);
  map.on('focus', function () {{ map.scrollWheelZoom.enable(); }});
  map.on('blur', function () {{ map.scrollWheelZoom.disable(); }});
}})();
</script>"""
    else:
        map_html = (
            '<div class="empty">Nothing to pin yet — '
            '<a href="/observations/new">log a sighting with a location</a> '
            'and it\u2019ll show up here. 🗺️</div>'
        )
    body = f"""
<h2 class="section-title" style="margin-top:0">🗺️ Your sightings map</h2>
<p class="hint">Every sighting you\u2019ve logged with a location, on one map.</p>
<form class="search-bar" method="get" action="/map">
  <select name="species" aria-label="Filter by species">
    {"".join(opts)}
  </select>
  <button class="btn btn-secondary" type="submit">Filter</button>
  {f'<a href="/map" class="clear-link">Clear</a>' if selected_species else ""}
</form>
{map_html}
"""
    return layout("Sightings map", body)


def nearby_page(
    home: dict, taxa: list[dict], error: str | None = None, from_cache: bool = False
) -> str:
    """📍 "Around you right now" — species being seen near home."""
    place = home.get("name") or "your home"
    if error == "no_home_location":
        body = """
<h2 class="section-title" style="margin-top:0">📍 Around you right now</h2>
<div class="empty">
  Tell me where home is and I\u2019ll show you what wildlife is being seen nearby.
  <br><br><a class="btn" href="/settings">📍 Set your home location</a>
</div>
"""
        return layout("Nearby", body)
    if error == "fetch_failed":
        note = "The wildlife database isn\u2019t answering right now — try again in a bit."
    elif not taxa:
        note = "No recent nearby observations in the wildlife database — check back soon."
    else:
        note = (
            f"{len(taxa)} species seen recently within 25 km of {_esc(place)}"
            + (" · cached" if from_cache else "")
            + "."
        )
    cards = []
    for t in taxa:
        common = t.get("common_name") or t.get("scientific_name") or "Unknown"
        sci = t.get("scientific_name") or ""
        n = t.get("recent_count") or 0
        photo = t.get("photo_url")
        img = (
            f'<img src="{_esc(photo)}" alt="{_esc(common)}" loading="lazy">'
            if photo
            else '<div class="no-photo">🦌</div>'
        )
        log_href = "/observations/new?" + urlencode(
            {
                "species_name": t.get("common_name") or t.get("scientific_name") or "",
                "scientific_name": t.get("scientific_name") or "",
            }
        )
        cards.append(f"""
<article class="card nearby-card" data-taxon-id="{_esc(t.get('taxon_id'))}"
         data-common="{_esc(t.get('common_name') or '')}"
         data-scientific="{_esc(sci)}">
  {img}
  <div class="card-body">
    <h3>{_esc(common)}</h3>
    <div class="sci">{_esc(sci)}</div>
    <div class="meta">👀 {n} recent nearby observation{'s' if n != 1 else ''}</div>
    <div class="card-actions">
      <a class="edit-link" href="{_esc(log_href)}">＋ Log it</a>
      <button class="edit-link wishlist-add" type="button">＋ Wishlist</button>
    </div>
    <div class="wishlist-msg"></div>
  </div>
</article>""")
    grid = '<div class="cards">\n' + "\n".join(cards) + "\n</div>" if cards else ""
    body = f"""
<h2 class="section-title" style="margin-top:0">📍 Around you right now</h2>
<p class="hint">{note}</p>
{grid}
<script>
(function () {{
  document.querySelectorAll('.wishlist-add').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      var card = btn.closest('.nearby-card');
      var msg = card.querySelector('.wishlist-msg');
      btn.disabled = true;
      fetch('/api/wishlist', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          scientific_name: card.dataset.scientific || null,
          common_name: card.dataset.common || null,
          taxon_id: card.dataset.taxonId ? parseInt(card.dataset.taxonId, 10) : null
        }})
      }}).then(function (r) {{
        if (r.status === 409) throw new Error('Already on your wishlist ⭐');
        if (!r.ok) throw new Error('Could not add it.');
        msg.innerHTML = '<div class="notice">✓ Added to your <a href="/wishlist">wishlist</a>.</div>';
      }}).catch(function (ex) {{
        msg.innerHTML = '<div class="notice">' + ex.message + '</div>';
        btn.disabled = false;
      }});
    }});
  }});
}})();
</script>
"""
    return layout("Nearby", body)


def wishlist_page(items: list[dict]) -> str:
    """⭐ Wishlist — species she'd love to find."""
    cards = []
    for w in items:
        common = w.get("common_name") or w.get("scientific_name") or "Unknown"
        sci = w.get("scientific_name") or ""
        photo = w.get("photo_url")
        img = (
            f'<img src="{_esc(photo)}" alt="{_esc(common)}" loading="lazy">'
            if photo
            else '<div class="no-photo">⭐</div>'
        )
        seen = '<span class="seen-badge">Seen ✓</span>' if w.get("seen") else ""
        range_link = (
            f'<a class="edit-link" href="{_esc(w["range_href"])}">🗺️ Range map</a>'
            if w.get("range_href")
            else ""
        )
        notes = _esc(w.get("notes") or "")
        cards.append(f"""
<article class="card" data-wishlist="{w['id']}">
  {img}
  <div class="card-body">
    <h3>{_esc(common)}{seen}</h3>
    <div class="sci">{_esc(sci)}</div>
    {f'<div class="notes">{notes}</div>' if notes else ""}
    <div class="card-actions">
      {range_link}
      <button class="edit-link wishlist-remove" type="button" data-remove="{w['id']}">🗑️ Remove</button>
    </div>
  </div>
</article>""")
    grid = (
        '<div class="cards">\n' + "\n".join(cards) + "\n</div>"
        if cards
        else '<div class="empty">Nothing on the wishlist yet — add something you\u2019d love to spot. ⭐</div>'
    )
    body = f"""
<h2 class="section-title" style="margin-top:0">⭐ Wishlist</h2>
<p class="hint">Species you\u2019d love to find. When you log one, it gets a <b>Seen ✓</b> badge all by itself.</p>
<div class="form-card">
  <div class="error" id="wish-error"></div>
  <form id="wish-form">
    <div class="field">
      <label for="wish-species">Add a species</label>
      <input type="text" id="wish-species" placeholder="Start typing — e.g. painted bunting" autocomplete="off">
      <input type="hidden" id="wish-scientific">
      <input type="hidden" id="wish-taxon">
      <div class="autocomplete" id="wish-ac"></div>
    </div>
    <div class="field">
      <label for="wish-notes">Notes (optional)</label>
      <input type="text" id="wish-notes" placeholder="Heard one near the river last spring…">
    </div>
    <button class="btn" type="submit">＋ Add to wishlist</button>
  </form>
</div>
<h3 class="section-title">Your list</h3>
{grid}
<script>
(function () {{
  var input = document.getElementById('wish-species');
  var sci = document.getElementById('wish-scientific');
  var taxon = document.getElementById('wish-taxon');
  var list = document.getElementById('wish-ac');
  var timer = null;
  function close() {{ list.classList.remove('open'); list.innerHTML = ''; }}
  input.addEventListener('input', function () {{
    sci.value = ''; taxon.value = '';
    clearTimeout(timer);
    var q = input.value.trim();
    if (q.length < 2) {{ close(); return; }}
    timer = setTimeout(function () {{
      fetch('/api/species/search?q=' + encodeURIComponent(q) + '&per_page=6')
        .then(function (r) {{ return r.json(); }})
        .then(function (data) {{
          var results = (data && data.results) || [];
          if (!results.length) {{ close(); return; }}
          list.innerHTML = '';
          results.forEach(function (t) {{
            var item = document.createElement('div');
            item.className = 'ac-item';
            var img = t.photo_url ? '<img src="' + t.photo_url.replace(/"/g, '') + '" alt="">' : '<img alt="">';
            item.innerHTML = img + '<div class="names"><div class="common"></div><div class="sci"></div></div>';
            item.querySelector('.common').textContent = t.common_name || t.scientific_name || 'Unknown';
            item.querySelector('.sci').textContent = t.scientific_name || '';
            item.addEventListener('mousedown', function (e) {{
              e.preventDefault();
              input.value = t.common_name || t.scientific_name || '';
              sci.value = t.scientific_name || '';
              taxon.value = t.id || '';
              close();
            }});
            list.appendChild(item);
          }});
          list.classList.add('open');
        }})
        .catch(function () {{ close(); }});
    }}, 250);
  }});
  document.addEventListener('click', function (e) {{
    if (!list.contains(e.target) && e.target !== input) close();
  }});
  document.getElementById('wish-form').addEventListener('submit', function (e) {{
    e.preventDefault();
    var err = document.getElementById('wish-error');
    err.classList.remove('show');
    var payload = {{
      scientific_name: sci.value || null,
      common_name: input.value.trim() || null,
      taxon_id: taxon.value ? parseInt(taxon.value, 10) : null,
      notes: document.getElementById('wish-notes').value.trim() || null
    }};
    if (!payload.common_name && !payload.scientific_name) {{
      err.textContent = 'Name a species first.';
      err.classList.add('show');
      return;
    }}
    fetch('/api/wishlist', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify(payload)
    }}).then(function (r) {{
      if (r.status === 409) throw new Error('That one\u2019s already on your wishlist.');
      if (!r.ok) throw new Error('Could not add it.');
      window.location.reload();
    }}).catch(function (ex) {{
      err.textContent = ex.message;
      err.classList.add('show');
    }});
  }});
  document.querySelectorAll('[data-remove]').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      if (!confirm('Remove this from your wishlist?')) return;
      fetch('/api/wishlist/' + btn.getAttribute('data-remove'), {{ method: 'DELETE' }})
        .then(function (r) {{
          if (!r.ok) throw new Error('remove failed');
          var card = btn.closest('[data-wishlist]');
          if (card) card.remove();
        }})
        .catch(function () {{}});
    }});
  }});
}})();
</script>
"""
    return layout("Wishlist", body)
