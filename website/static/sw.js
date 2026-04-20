// A simple service worker to satisfy PWA installation requirements
self.addEventListener('install', (e) => {
    console.log('[Service Worker] Install');
});

self.addEventListener('fetch', (e) => {
    // Leave empty: bypasses caching, ensuring your dynamic data is always fresh
});