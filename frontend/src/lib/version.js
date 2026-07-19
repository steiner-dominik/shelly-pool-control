// Detect new releases and force a clean reload (cache purge + SW purge).
export const APP_VERSION = typeof __APP_VERSION__ !== "undefined" ? __APP_VERSION__ : "dev";

async function check() {
  try {
    const r = await fetch("/api/version", { cache: "no-store" });
    if (!r.ok) return;
    const { version } = await r.json();
    if (version && version !== APP_VERSION && APP_VERSION !== "dev") {
      if (navigator.serviceWorker?.controller) {
        navigator.serviceWorker.controller.postMessage("purge");
      }
      if ("caches" in window) {
        const keys = await caches.keys();
        await Promise.all(keys.map((k) => caches.delete(k)));
      }
      location.reload();
    }
  } catch {
    /* offline — ignore */
  }
}

export function startVersionWatch() {
  setInterval(check, 5 * 60 * 1000);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible") check();
  });
  setTimeout(check, 10_000);
}
