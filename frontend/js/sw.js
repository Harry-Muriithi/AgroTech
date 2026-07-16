// ═══════════════════════════════════════════════════════════
//  AGROTECH SERVICE WORKER  —  sw.js   (served from site root: /sw.js)
//  Strategy:
//    • API calls (Railway)  → always network, never cached (data stays fresh)
//    • Page navigations      → network first, fall back to cache, then offline page
//    • Static assets (css/js/img) → cache first, refreshed in the background
//  Bump CACHE_VERSION whenever you want users to get fresh cached files.
// ═══════════════════════════════════════════════════════════

const CACHE_VERSION = "agrotech-v1";
const API_HOST = "agrotech-75cy.onrender.com";

// App shell — cached on install so the app opens even offline.
const SHELL = [
  "/index.html",
  "/404.html",
  "/manifest.json",
  "/css/mobile.css",
  "/js/app.js",
  "/js/notifications.js",
  "/pages/dashboard.html",
  "/pages/scan.html",
  "/pages/history.html",
  "/pages/schedule.html",
  "/pages/inventory.html",
  "/pages/profit.html",
  "/pages/subscription.html",
  "/pages/profile.html",
  "/icons/icon-192.png",
  "/icons/icon-512.png"
];

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_VERSION).then(function (cache) {
      // addAll fails if any single file 404s, so add them tolerantly.
      return Promise.all(SHELL.map(function (url) {
        return cache.add(url).catch(function () { /* skip missing */ });
      }));
    }).then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.map(function (k) {
        if (k !== CACHE_VERSION) return caches.delete(k);
      }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (event) {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle GET; let POST/PUT/DELETE go straight to network.
  if (req.method !== "GET") return;

  // Never cache API data — always go to the network.
  if (url.hostname === API_HOST) return;

  // Page navigations: network first, fall back to cache, then offline shell.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req).then(function (res) {
        const copy = res.clone();
        caches.open(CACHE_VERSION).then(function (c) { c.put(req, copy); });
        return res;
      }).catch(function () {
        return caches.match(req).then(function (hit) {
          return hit || caches.match("/404.html");
        });
      })
    );
    return;
  }

  // Static assets: cache first, refresh in background (stale-while-revalidate).
  event.respondWith(
    caches.match(req).then(function (hit) {
      const network = fetch(req).then(function (res) {
        if (res && res.status === 200) {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then(function (c) { c.put(req, copy); });
        }
        return res;
      }).catch(function () { return hit; });
      return hit || network;
    })
  );
});
