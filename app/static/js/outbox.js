/* Fauna offline outbox — queues sightings in IndexedDB when there's no
 * signal, then syncs them through the normal API when back online.
 *
 * Plain script (no modules): exposes window.FaunaOutbox. The pure helpers
 * (dataUrlToParts, syncEntry) take no browser APIs beyond atob/Blob and are
 * unit-tested under node; the IndexedDB + fetch glue lives in the page.
 */
(function (global) {
  'use strict';

  var DB_NAME = 'fauna-outbox';
  var STORE = 'sightings';

  function openDb() {
    return new Promise(function (resolve, reject) {
      if (!('indexedDB' in global)) {
        reject(new Error('no indexedDB'));
        return;
      }
      var req = global.indexedDB.open(DB_NAME, 1);
      req.onupgradeneeded = function () {
        req.result.createObjectStore(STORE, { keyPath: 'id', autoIncrement: true });
      };
      req.onsuccess = function () {
        resolve(req.result);
      };
      req.onerror = function () {
        reject(req.error);
      };
    });
  }

  function store(db, mode) {
    return db.transaction(STORE, mode).objectStore(STORE);
  }

  function savePending(db, entry) {
    return new Promise(function (resolve, reject) {
      var copy = {
        payload: entry.payload,
        photos: entry.photos || [],
        savedAt: new Date().toISOString(),
      };
      var req = store(db, 'readwrite').add(copy);
      req.onsuccess = function () {
        resolve(req.result);
      };
      req.onerror = function () {
        reject(req.error);
      };
    });
  }

  function listPending(db) {
    return new Promise(function (resolve, reject) {
      var req = store(db, 'readonly').getAll();
      req.onsuccess = function () {
        resolve(req.result || []);
      };
      req.onerror = function () {
        reject(req.error);
      };
    });
  }

  function removePending(db, id) {
    return new Promise(function (resolve, reject) {
      var req = store(db, 'readwrite').delete(id);
      req.onsuccess = function () {
        resolve();
      };
      req.onerror = function () {
        reject(req.error);
      };
    });
  }

  function countPending(db) {
    return new Promise(function (resolve, reject) {
      var req = store(db, 'readonly').count();
      req.onsuccess = function () {
        resolve(req.result || 0);
      };
      req.onerror = function () {
        reject(req.error);
      };
    });
  }

  // -- pure helpers (node-testable) ---------------------------------------

  /** Split a data: URL into {mime, base64}. Throws on malformed input. */
  function dataUrlToParts(dataUrl) {
    var m = /^data:([^;,]+)?(;base64)?,(.*)$/.exec(dataUrl || '');
    if (!m || m[2] !== ';base64') throw new Error('bad data URL');
    return { mime: m[1] || 'application/octet-stream', base64: m[3] };
  }

  /** base64 parts -> Blob (browser). Kept separate so tests can stop at parts. */
  function partsToBlob(parts) {
    var bin = global.atob(parts.base64);
    var bytes = new Uint8Array(bin.length);
    for (var i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new Blob([bytes], { type: parts.mime });
  }

  /**
   * Push one queued entry through the API.
   * http = { postJson(url, obj) -> Promise<{ok, body}>,
   *          postPhotos(obsId, photos) -> Promise<{ok, body}> }
   * photos are [{name, dataUrl}]. Resolves to the final observation body.
   */
  function syncEntry(entry, http) {
    var payload = {};
    Object.keys(entry.payload || {}).forEach(function (k) {
      if (k !== 'photo_path') payload[k] = entry.payload[k];
    });
    return http.postJson('/api/observations', payload).then(function (res) {
      if (!res.ok || !res.body || !res.body.id) throw new Error('sighting sync failed');
      var photos = entry.photos || [];
      if (!photos.length) return res.body;
      return http.postPhotos(res.body.id, photos).then(function (r2) {
        if (!r2.ok) throw new Error('photo sync failed');
        return r2.body;
      });
    });
  }

  /**
   * Sync every queued entry; successes are removed from the outbox.
   * onProgress(done, total) is optional. Resolves {synced, failed}.
   */
  function syncAll(db, http, onProgress) {
    return listPending(db).then(function (entries) {
      var synced = 0;
      var failed = 0;
      var chain = Promise.resolve();
      entries.forEach(function (entry) {
        chain = chain.then(function () {
          return syncEntry(entry, http).then(
            function () {
              synced++;
              return removePending(db, entry.id);
            },
            function () {
              failed++;
            }
          );
        }).then(function () {
          if (onProgress) onProgress(synced + failed, entries.length);
        });
      });
      return chain.then(function () {
        return { synced: synced, failed: failed };
      });
    });
  }

  global.FaunaOutbox = {
    openDb: openDb,
    savePending: savePending,
    listPending: listPending,
    removePending: removePending,
    countPending: countPending,
    dataUrlToParts: dataUrlToParts,
    partsToBlob: partsToBlob,
    syncEntry: syncEntry,
    syncAll: syncAll,
  };
})(typeof window !== 'undefined' ? window : globalThis);
