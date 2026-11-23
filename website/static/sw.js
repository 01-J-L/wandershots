/* WanderShots service worker.
 * Safe by default: never caches admin, booking, auth, or upload responses.
 */
'use strict';

const CACHE_VERSION = 'wandershots-v2-2026-11-22';
const STATIC_CACHE = `${CACHE_VERSION}-static`;
const RUNTIME_CACHE = `${CACHE_VERSION}-runtime`;
const OFFLINE_URL = '/offline';

const PRECACHE_URLS = [
    OFFLINE_URL,
    '/static/css/ui.css',
    '/static/js/loading-manager.js',
    '/static/js/network-status.js',
    '/static/js/performance.js',
    '/static/images/wslogo.png',
    '/static/favicon.ico',
    '/static/manifest.json'
];

const PUBLIC_NAV_PATHS = new Set(['/', '/about', '/services', '/works', '/contact', '/offline']);
const NEVER_CACHE_PREFIXES = [
    '/admin',
    '/dashboard',
    '/login',
    '/logout',
    '/register',
    '/reset',
    '/verify',
    '/booking',
    '/book',
    '/payment',
    '/gallery',
    '/api',
    '/chat',
    '/google',
    '/sw.js'
];
const CDN_HOSTS = new Set([
    'cdn.tailwindcss.com',
    'cdnjs.cloudflare.com',
    'cdn.jsdelivr.net',
    'fonts.googleapis.com',
    'fonts.gstatic.com'
]);

function isNeverCache(url) {
    return NEVER_CACHE_PREFIXES.some((prefix) => url.pathname === prefix || url.pathname.startsWith(`${prefix}/`));
}

function isCacheableAsset(url) {
    if (url.origin !== self.location.origin) {
        return CDN_HOSTS.has(url.hostname);
    }
    if (isNeverCache(url)) return false;
    if (url.pathname.startsWith('/static/css/') || url.pathname.startsWith('/static/js/')) return true;
    return [
        '/static/images/wslogo.png',
        '/static/favicon.ico',
        '/static/manifest.json'
    ].includes(url.pathname);
}

self.addEventListener('install', (event) => {
    event.waitUntil((async () => {
        const cache = await caches.open(STATIC_CACHE);
        await Promise.all(PRECACHE_URLS.map(async (url) => {
            try {
                await cache.add(new Request(url, { cache: 'reload' }));
            } catch (error) {
                // A single missing asset must not block the whole install.
            }
        }));
        await self.skipWaiting();
    })());
});

self.addEventListener('activate', (event) => {
    event.waitUntil((async () => {
        const keys = await caches.keys();
        await Promise.all(keys
            .filter((key) => key.startsWith('wandershots-') && !key.startsWith(CACHE_VERSION))
            .map((key) => caches.delete(key)));
        await self.clients.claim();
    })());
});

self.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'SKIP_WAITING') {
        self.skipWaiting();
    }
});

async function networkFirstNavigation(request) {
    const url = new URL(request.url);
    const cache = await caches.open(RUNTIME_CACHE);
    const network = fetch(request).then((response) => {
        if (response && response.ok && PUBLIC_NAV_PATHS.has(url.pathname)) {
            cache.put(request, response.clone()).catch(() => {});
        }
        return response;
    });

    try {
        return await Promise.race([
            network,
            new Promise((_, reject) => setTimeout(() => reject(new Error('navigation-timeout')), 3800))
        ]);
    } catch (error) {
        const cached = await cache.match(request);
        if (cached) return cached;
        const offline = await caches.match(OFFLINE_URL);
        if (offline) return offline;
        return new Response('You are offline.', {
            status: 503,
            headers: { 'Content-Type': 'text/plain; charset=utf-8' }
        });
    }
}

async function staleWhileRevalidate(request) {
    const cache = await caches.open(RUNTIME_CACHE);
    const cached = await cache.match(request);
    const network = fetch(request).then((response) => {
        if (response && (response.ok || response.type === 'opaque')) {
            cache.put(request, response.clone()).catch(() => {});
        }
        return response;
    }).catch(() => null);

    if (cached) {
        network.catch(() => {});
        return cached;
    }
    const response = await network;
    if (response) return response;
    return new Response('', { status: 504, statusText: 'Offline' });
}

self.addEventListener('fetch', (event) => {
    const request = event.request;
    if (request.method !== 'GET') return;

    const url = new URL(request.url);

    if (request.mode === 'navigate') {
        event.respondWith(networkFirstNavigation(request));
        return;
    }

    if (isNeverCache(url)) return;

    if (isCacheableAsset(url)) {
        event.respondWith(staleWhileRevalidate(request));
    }
});
