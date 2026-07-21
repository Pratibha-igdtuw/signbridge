/* SignBridge Service Worker — app-shell caching for offline use.
   Network-first for API calls (so data is always fresh when online),
   cache-first for static assets and the MediaPipe CDN scripts (so
   gesture recognition still works with no connection). Served at /sw.js
   (see app.py) so its default scope covers the whole site, not just /static/. */

const CACHE_NAME = 'signbridge-shell-v1';

const SHELL_URLS = [
  '/', '/for-you', '/learn', '/emergency', '/live', '/history', '/gestures-page', '/analytics-page',
  '/static/css/style.css', '/static/css/home.css', '/static/css/landing.css',
  '/static/js/app.js', '/static/js/practice.js', '/static/js/emergency.js', '/static/js/live.js',
  '/static/js/offline.js',
  // MediaPipe (hand-tracking) — without these cached, camera-based recognition can't
  // start at all when offline, since they're normally loaded from a CDN.
  'https://cdn.jsdelivr.net/npm/@mediapipe/camera_utils/camera_utils.js',
  'https://cdn.jsdelivr.net/npm/@mediapipe/drawing_utils/drawing_utils.js',
  'https://cdn.jsdelivr.net/npm/@mediapipe/hands/hands.js',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      Promise.allSettled(SHELL_URLS.map((url) => cache.add(url).catch(() => null)))
    ).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Never intercept POST/DELETE/etc — those must always hit the network (or be
  // queued client-side by offline.js) so we don't silently swallow writes.
  if (req.method !== 'GET') return;

  const isApi = url.pathname.startsWith('/api/');

  if (isApi) {
    // Network-first for API data, so logged-in state / fresh stats always win when online.
    event.respondWith(
      fetch(req).then((res) => {
        const copy = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
        return res;
      }).catch(() => caches.match(req))
    );
    return;
  }

  // Cache-first for the app shell and CDN scripts.
  event.respondWith(
    caches.match(req).then((cached) => cached || fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
      return res;
    }).catch(() => cached))
  );
});