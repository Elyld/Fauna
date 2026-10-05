"""Server-rendered HTML pages for Fauna (teddy-bear theme).

The JSON API in app/main.py is untouched; these pages are a thin,
human-friendly layer on top of it.
"""
from __future__ import annotations

import html
from datetime import datetime
from urllib.parse import urlencode

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
    <a href="/stats">📊 Stats</a>
    <a href="/identify">🔍 Identify</a>
    <a href="/identify-audio">🎵 Sound ID</a>
    <a href="/import">⬆️ Import</a>
    <a href="/observations/new">+ Log a sighting</a>
    <a href="/settings">⚙️ Settings</a>
  </nav>
</header>
<main class="wrap">
{body}
</main>
<nav class="tabbar" aria-label="Primary">
  <a href="/">🏠<span>Home</span></a>
  <a href="/observations">🐾<span>Sightings</span></a>
  <a href="/identify">🔍<span>Identify</span></a>
  <a href="/identify-audio">🎵<span>Sound</span></a>
</nav>
<footer>{APP_NAME} · a wildlife observation journal</footer>
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
            cards.append(f"""
<article class="card life-card">
  {img}
  <div class="card-body">
    <h3>{_esc(r["species_name"])}</h3>
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
        msg.innerHTML = '<div class="notice">Couldn't save — please try again.</div>';
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
    existing_photo = prefill.get("existing_photo")
    needs_id_checked = "checked" if prefill.get("needs_id") else ""
    title = "Edit sighting" if is_edit else "Log a sighting"
    button = "Save changes" if is_edit else "Save sighting"

    camera_block = """
    <div class="field">
      <label class="photo-btn" for="photo">📸<span>Take a photo</span></label>
      <input type="file" id="photo" name="photo" accept="image/*" capture="environment" style="display:none">
      <img id="photo-preview" class="photo-preview" alt="Photo preview" style="display:none">
      <div class="hint">Camera opens right away — or pick one from your gallery.</div>
    </div>"""
    if is_edit and existing_photo:
        photo_block = f"""
    <div class="field">
      <label>Photo</label>
      <img src="{_esc(existing_photo)}" class="photo-preview" alt="Sighting photo">
      <label class="photo-btn" for="photo" style="margin-top:0.6rem">📸<span>Replace photo</span></label>
      <input type="file" id="photo" name="photo" accept="image/*" capture="environment" style="display:none">
      <img id="photo-preview" class="photo-preview" alt="New photo preview" style="display:none">
    </div>"""
    elif is_edit:
        photo_block = camera_block
    elif pending:
        photo_block = f"""
    <div class="field">
      <label>Photo</label>
      <img src="{_esc(pending['url'])}" class="photo-preview" alt="Sighting photo">
      <input type="hidden" id="pending-photo" value="{_esc(pending['path'])}">
      <div class="hint">From your identification — it'll be saved with this sighting.</div>
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

  // Photo preview for the camera button.
  var photoInput = document.getElementById('photo');
  var photoPreview = document.getElementById('photo-preview');
  if (photoInput && photoPreview) {{
    photoInput.addEventListener('change', function () {{
      if (!photoInput.files.length) return;
      photoPreview.src = URL.createObjectURL(photoInput.files[0]);
      photoPreview.style.display = '';
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
    {save_js}
    // A freshly picked file uploads the classic way after the record saves;
    // a pending photo from Identify rides along in the payload instead.
    var file = photoInput && photoInput.files[0];
    saveObservation()
      .then(function (res) {{
        if (!res.ok) throw new Error('Could not save the sighting.');
        if (!file) {{ window.location = '/observations'; return; }}
        var fd = new FormData();
        fd.append('file', file);
        return fetch('/api/observations/' + res.body.id + '/photo', {{ method: 'POST', body: fd }})
          .then(function () {{ window.location = '/observations'; }});
      }})
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
            "existing_photo": obs.get("photo_url"),
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
