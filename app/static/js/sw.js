/* Fauna service worker — offline mode.
 *
 * Strategy:
 *   /photos/*, /static/*, /manifest.json, /sw.js  -> cache-first
 *   /api/* (GET)                                  -> network-first, no cache
 *   page navigations                              -> network-first, cache fallback
 *   POST/PUT/DELETE                               -> always network (the outbox
 *                                                    in outbox.js queues the quick-log)
 * Cross-origin requests (map tiles, CDNs) are left alone.
 */
const CACHE = 'fauna-v1';
const SHELL = [
  '/',
  '/static/css/theme.css',
  '/static/img/icon.svg',
  '/static/img/icon-192.png',
  '/static/img/icon-512.png',
  '/static/img/apple-touch-icon.png',
  '/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
      )
      .then(() => self.clients.claim())
  );
});

function cacheFirst(request) {
  return caches.match(request).then(
    (hit) =>
      hit ||
      fetch(request).then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(request, copy));
        return res;
      })
  );
}

function networkFirstPage(request) {
  return fetch(request)
    .then((res) => {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(request, copy));
      return res;
    })
    .catch(() =>
      caches.match(request).then((hit) => hit || caches.match('/'))
    );
}

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return; // mutations always go to the network
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return; // tiles/CDNs: browser handles

  const path = url.pathname;
  if (
    path.startsWith('/photos/') ||
    path.startsWith('/static/') ||
    path === '/manifest.json' ||
    path === '/sw.js'
  ) {
    event.respondWith(cacheFirst(req));
    return;
  }
  if (path.startsWith('/api/')) {
    // Fresh data only; when offline the page shows its own "you're offline" note.
    event.respondWith(
      fetch(req).catch(
        () =>
          new Response(JSON.stringify({ error: 'offline' }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          })
      )
    );
    return;
  }
  event.respondWith(networkFirstPage(req));
});
