var CACHE = 'agenda-arthur-v8';
// URLs relativas ao escopo do SW (em GitHub Pages project site o scope
// é /<repo>/, então './' aponta corretamente em vez de '/').
var URLS = ['./', './index.html', './manifest.json'];

self.addEventListener('install', function(e) {
  // Cache best-effort — se algum URL falhar, NÃO bloqueia o install.
  // (caches.addAll rejeita o batch inteiro se qualquer um falhar; usamos
  // Promise.allSettled com puts individuais pra tolerar 404.)
  e.waitUntil(
    caches.open(CACHE).then(function(c) {
      return Promise.allSettled(URLS.map(function(u) {
        return fetch(u, { cache: 'no-cache' }).then(function(r) {
          if (r.ok) return c.put(u, r);
        });
      }));
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(e) {
  e.waitUntil(
    caches.keys().then(function(names) {
      return Promise.all(
        names.filter(function(n) { return n !== CACHE; }).map(function(n) { return caches.delete(n); })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(e) {
  if (e.request.url.includes('googleapis.com') || e.request.url.includes('accounts.google.com')) {
    return;
  }
  // Network-first: serve fresh content when online, fall back to cache when offline.
  // The cache is refreshed on every successful fetch so the offline copy stays current.
  if (e.request.method !== 'GET') return;
  e.respondWith(
    fetch(e.request).then(function(r) {
      if (r && r.ok) {
        var copy = r.clone();
        caches.open(CACHE).then(function(c) { c.put(e.request, copy); });
      }
      return r;
    }).catch(function() {
      return caches.match(e.request);
    })
  );
});

self.addEventListener('push', function(e) {
  var data = {};
  try { data = e.data ? e.data.json() : {}; } catch(err) {}
  e.waitUntil(
    self.registration.showNotification(data.title || 'Plantão HVC', {
      body: data.body || '',
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      requireInteraction: false
    })
  );
});
