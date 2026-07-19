// Service worker: cache-first for immutable hashed assets, network-first for
// everything else. The app itself detects new versions via /api/version and
// triggers a hard reload + cache purge (see store.js), so stale UIs never
// survive a release.
const RUNTIME = "pool-runtime-v1";

self.addEventListener("install", (e) => {
  self.skipWaiting();
});

self.addEventListener("activate", (e) => {
  e.waitUntil(self.clients.claim());
});

self.addEventListener("message", (e) => {
  if (e.data === "purge") {
    e.waitUntil(caches.keys().then((keys) =>
      Promise.all(keys.map((k) => caches.delete(k)))));
  }
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // never cache API

  if (url.pathname.startsWith("/assets/")) {
    // hashed filenames → safe to cache forever
    e.respondWith(
      caches.open(RUNTIME).then(async (cache) => {
        const hit = await cache.match(e.request);
        if (hit) return hit;
        const res = await fetch(e.request);
        if (res.ok) cache.put(e.request, res.clone());
        return res;
      })
    );
    return;
  }

  // network-first with offline fallback for the shell
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        if (res.ok && (url.pathname === "/" || url.pathname === "/index.html")) {
          const copy = res.clone();
          caches.open(RUNTIME).then((c) => c.put(e.request, copy));
        }
        return res;
      })
      .catch(() => caches.match(e.request).then((hit) => hit
        || caches.match("/")))
  );
});
