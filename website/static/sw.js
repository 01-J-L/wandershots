const CACHE_NAME = 'wandershots-cache-v1';
const ASSETS = [
  '/',
  '/static/apps/',
  '/offline' // Optional offline route
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS);
    })
  );
});

self.addEventListener('fetch', (e) => {
  e.respondWith(
    caches.match(e.request).then((response) => {
      return response || fetch(e.request).catch(() => caches.match('/offline'));
    })
  );
});