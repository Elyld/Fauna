"""Server-rendered HTML pages for Fauna (pink theme).

The JSON API in app/main.py is untouched; these pages are a thin,
human-friendly layer on top of it.
"""
from __future__ import annotations

import html
from datetime import datetime

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
  <a class="brand" href="/">🌸 {APP_NAME}</a>
  <nav>
    <a href="/">Home</a>
    <a href="/observations">Observations</a>
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
    notes = obs.get("notes") or ""
    snippet = _esc(notes[:110] + ("…" if len(notes) > 110 else ""))
    return f"""
<article class="card">
  {img}
  <div class="card-body">
    <h3>{_esc(obs.get("species_name") or "Unknown visitor")}{badge}</h3>
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
  <h1>🌸 {APP_NAME}</h1>
  <p class="tagline">Every squirrel, songbird, and bunny — noticed, named, and remembered.</p>
  <div class="stats">
    <div class="stat"><div class="num">{total}</div><div class="label">observations</div></div>
    <div class="stat"><div class="num">{species}</div><div class="label">species</div></div>
  </div>
  <a class="btn" href="/observations/new">+ Log a sighting</a>
  &nbsp;
  <a class="btn btn-secondary" href="/observations">Browse observations</a>
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


def new_observation_page() -> str:
    body = """
<h2 class="section-title" style="margin-top:0">Log a sighting</h2>
<div class="form-card">
  <div class="error" id="form-error"></div>
  <form id="obs-form">
    <div class="field">
      <label for="species">What did you see?</label>
      <input type="text" id="species" name="species_name" placeholder="Start typing — e.g. squirrel" autocomplete="off">
      <input type="hidden" id="scientific" name="scientific_name">
      <div class="autocomplete" id="ac-list"></div>
      <div class="hint">Suggestions come from the iNaturalist wildlife database.</div>
    </div>
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
      <textarea id="notes" name="notes" placeholder="What was it doing? Anything charming?"></textarea>
    </div>
    <div class="field">
      <label for="photo">Photo</label>
      <input type="file" id="photo" name="photo" accept="image/*">
    </div>
    <button class="btn" type="submit">Save sighting</button>
  </form>
</div>
<script>
(function () {
  var input = document.getElementById('species');
  var sci = document.getElementById('scientific');
  var list = document.getElementById('ac-list');
  var timer = null;

  function close() { list.classList.remove('open'); list.innerHTML = ''; }

  input.addEventListener('input', function () {
    sci.value = '';
    clearTimeout(timer);
    var q = input.value.trim();
    if (q.length < 2) { close(); return; }
    timer = setTimeout(function () {
      fetch('/api/species/search?q=' + encodeURIComponent(q) + '&per_page=6')
        .then(function (r) { return r.json(); })
        .then(function (data) {
          var results = (data && data.results) || [];
          if (!results.length) { close(); return; }
          list.innerHTML = '';
          results.forEach(function (t) {
            var item = document.createElement('div');
            item.className = 'ac-item';
            var img = t.photo_url
              ? '<img src="' + t.photo_url.replace(/"/g, '') + '" alt="">'
              : '<img alt="">';
            item.innerHTML = img +
              '<div class="names"><div class="common"></div><div class="sci"></div></div>';
            item.querySelector('.common').textContent = t.common_name || t.scientific_name || 'Unknown';
            item.querySelector('.sci').textContent = t.scientific_name || '';
            item.addEventListener('mousedown', function (e) {
              e.preventDefault();
              input.value = t.common_name || t.scientific_name || '';
              sci.value = t.scientific_name || '';
              close();
            });
            list.appendChild(item);
          });
          list.classList.add('open');
        })
        .catch(function () { close(); });
    }, 250);
  });

  document.addEventListener('click', function (e) {
    if (!list.contains(e.target) && e.target !== input) close();
  });

  document.getElementById('obs-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var err = document.getElementById('form-error');
    err.classList.remove('show');
    var observed = document.getElementById('observed_at').value;
    var payload = {
      species_name: input.value.trim() || null,
      scientific_name: sci.value || null,
      count: parseInt(document.getElementById('count').value, 10) || 1,
      observed_at: observed ? new Date(observed).toISOString() : null,
      location_name: document.getElementById('location').value.trim() || null,
      notes: document.getElementById('notes').value.trim() || null
    };
    fetch('/api/observations', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json().then(function (b) { return { ok: r.ok, body: b }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error('Could not save the sighting.');
        var file = document.getElementById('photo').files[0];
        if (!file) { window.location = '/observations'; return; }
        var fd = new FormData();
        fd.append('file', file);
        return fetch('/api/observations/' + res.body.id + '/photo', { method: 'POST', body: fd })
          .then(function () { window.location = '/observations'; });
      })
      .catch(function (ex) {
        err.textContent = ex.message || 'Something went wrong.';
        err.classList.add('show');
      });
  });
})();
</script>
"""
    return layout("Log a sighting", body)
