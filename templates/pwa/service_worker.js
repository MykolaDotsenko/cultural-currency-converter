{% load static %}
const CACHE_PREFIX = "cultural-currency-shell-";
const CACHE_VERSION = "v1";
const SHELL_CACHE = `${CACHE_PREFIX}${CACHE_VERSION}`;
const PRIVATE_TRIP_CACHE = "cultural-currency-private-trip-v1";
const OFFLINE_URL = "{{ offline_url|escapejs }}";
const STATIC_URL = "{{ static_url|escapejs }}";
const PRECACHE_URLS = [
  OFFLINE_URL,
  "{% static 'pwa/icon-192.png' %}",
  "{% static 'pwa/icon-512.png' %}",
  "{% static 'pwa/offline-shell.js' %}",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(SHELL_CACHE).then((cache) => cache.addAll(PRECACHE_URLS)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(CACHE_PREFIX) && key !== SHELL_CACHE)
            .map((key) => caches.delete(key)),
        ),
      )
      .then(() => self.clients.claim()),
  );
});

function isPublicStaticPath(url) {
  if (url.origin !== self.location.origin) return false;
  return (
    url.pathname.startsWith(`${STATIC_URL}build/`) ||
    url.pathname.startsWith(`${STATIC_URL}pwa/`)
  );
}

function offlineSnapshotPathForNavigation(pathname) {
  const detail = pathname.match(/^\/saved\/scenarios\/(\d+)\/$/);
  if (detail) return `/saved/scenarios/${detail[1]}/offline-snapshot/`;

  const snapshot = pathname.match(/^\/saved\/scenarios\/(\d+)\/offline-snapshot\/$/);
  return snapshot ? pathname : null;
}

async function offlineNavigationResponse(url) {
  const snapshotPath = offlineSnapshotPathForNavigation(url.pathname);
  if (snapshotPath) {
    const privateCache = await caches.open(PRIVATE_TRIP_CACHE);
    const snapshotUrl = new URL(snapshotPath, self.location.origin).toString();
    const privateSnapshot = await privateCache.match(snapshotUrl);
    if (privateSnapshot) return privateSnapshot;
  }

  const shell = await caches.match(OFFLINE_URL);
  if (shell) return shell;

  return new Response("Offline", {
    status: 503,
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}

async function publicStaticResponse(request) {
  const cached = await caches.match(request);
  if (cached) return cached;

  const response = await fetch(request);
  if (response.ok && response.type === "basic") {
    const cache = await caches.open(SHELL_CACHE);
    await cache.put(request, response.clone());
  }
  return response;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    // Navigation HTML is always network-only. This deliberately prevents
    // account, SavedScenario, notification, admin or form responses from
    // entering Cache Storage. Offline navigation falls back to a generic,
    // non-personalized shell.
    event.respondWith(fetch(request).catch(() => offlineNavigationResponse(url)));
    return;
  }

  if (isPublicStaticPath(url)) {
    event.respondWith(publicStaticResponse(request));
  }
});
