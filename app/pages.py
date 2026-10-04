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
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)} · {APP_NAME}</title>
<link rel="stylesheet" href="/static/css/theme.css">
</head>
<body>
<header class="site-header">
  <a class="brand" href="/">🧸 {APP_NAME}</a>
  <nav>
    <a href="/">Home</a>
    <a href="/observations">Observations</a>
    <a href="/identify">🔍 Identify</a>
    <a href="/identify-audio">🎵 Sound ID</a>
    <a href="/observations/new">+ Log a sighting</a>
  </nav>
</header>
<main class="wrap">
{body}
</main>
<footer>{APP_NAME} · a wildlife observation journal</footer>
</body>
</html>"""


def card(obs: dict) -> str:
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
    return f"""
<article class="card">
  {img}
  <div class="card-body">
    <h3>{_esc(obs.get("species_name") or "Unknown visitor")}{badge}{needs_id}</h3>
    <div class="sci">{_esc(obs.get("scientific_name") or "")}</div>
    <div class="meta">📅 {_esc(_fmt_date(obs.get("observed_at")))} · 📍 {_esc(obs.get("location_name") or "Somewhere lovely")}</div>
    {f'<div class="notes">{snippet}</div>' if snippet else ""}
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
    <div class="stat"><div class="num">{species}</div><div class="label">species</div></div>
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


def observations_page(observations: list[dict]) -> str:
    if observations:
        grid = '<div class="cards">\n' + "\n".join(card(o) for o in observations) + "\n</div>"
    else:
        grid = (
            '<div class="empty">Nothing here yet. '
            '<a href="/observations/new">Log your first sighting</a> 🐇</div>'
        )
    body = f"""
<h2 class="section-title" style="margin-top:0">Observations</h2>
{grid}
"""
    return layout("Observations", body)


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
    <input type="file" id="photo-input" accept="image/*" style="display:none">
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
  <div class="spinner"><span class="big">🔍</span>Asking iNaturalist what this might be…</div>
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
        'It needs a quick one-time setup (an iNaturalist link). ' +
        'You can still log this sighting manually below — your photo is saved and ready.</div>';
    } else if (data.error === 'inat_unreachable') {
      notice.innerHTML = '<div class="notice">📡 <strong>iNaturalist didn\\'t answer.</strong> ' +
        'Check your connection and try again, or log it manually below.</div>';
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


def new_observation_page(prefill: dict | None = None) -> str:
    prefill = prefill or {}
    species = _esc(prefill.get("species_name") or "")
    scientific = _esc(prefill.get("scientific_name") or "")
    notes_prefill = _esc(prefill.get("notes") or "")
    pending = prefill.get("pending_photo")
    needs_id_checked = "checked" if prefill.get("needs_id") else ""

    if pending:
        photo_block = f"""
    <div class="field">
      <label>Photo</label>
      <img src="{_esc(pending['url'])}" class="photo-preview" alt="Sighting photo">
      <input type="hidden" id="pending-photo" value="{_esc(pending['path'])}">
      <div class="hint">From your identification — it'll be saved with this sighting.</div>
    </div>"""
        file_hint = '<div class="hint">Or replace it:</div>'
    else:
        photo_block = ""
        file_hint = ""

    body = f"""
<h2 class="section-title" style="margin-top:0">Log a sighting</h2>
<div class="form-card">
  <div class="error" id="form-error"></div>
  <form id="obs-form">
    <div class="field">
      <label for="species">What did you see?</label>
      <input type="text" id="species" name="species_name" placeholder="Start typing — e.g. squirrel" autocomplete="off" value="{species}">
      <input type="hidden" id="scientific" name="scientific_name" value="{scientific}">
      <div class="autocomplete" id="ac-list"></div>
      <div class="hint">Suggestions come from the iNaturalist wildlife database.</div>
    </div>
    <label class="checkbox-row">
      <input type="checkbox" id="needs-id" {needs_id_checked}>
      <span class="cb-text"><strong>I'm not sure what this is.</strong><br>Flag it so we remember the ID still needs confirming.</span>
    </label>
    <div class="form-row">
      <div class="field">
        <label for="count">How many?</label>
        <input type="number" id="count" name="count" min="1" value="1">
      </div>
      <div class="field">
        <label for="observed_at">When?</label>
        <input type="datetime-local" id="observed_at" name="observed_at">
      </div>
    </div>
    <div class="field">
      <label for="location">Where?</label>
      <input type="text" id="location" name="location_name" placeholder="Backyard oak, riverside trail…">
    </div>
    <div class="field">
      <label for="notes">Notes</label>
      <textarea id="notes" name="notes" placeholder="What was it doing? Anything charming?">{notes_prefill}</textarea>
    </div>
    {photo_block}
    <div class="field">
      <label for="photo">{"Add a photo" if not pending else "Photo"}</label>
      {file_hint}
      <input type="file" id="photo" name="photo" accept="image/*">
    </div>
    <button class="btn" type="submit">Save sighting</button>
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
    function saveObservation() {{
      return fetch('/api/observations', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(payload)
      }}).then(function (r) {{ return r.json().then(function (b) {{ return {{ ok: r.ok, body: b }}; }}); }});
    }}
    // If she picked a brand-new file now, upload it the classic way;
    // otherwise the pending photo from Identify rides along in the payload.
    var file = document.getElementById('photo').files[0];
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
    return layout("Log a sighting", body)
