const LOCAL_SERVICE_WORKER_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);
const PRIVATE_TRIP_CACHE_PREFIX = "cultural-currency-private-trip-";

function serviceWorkerEligible(): boolean {
  return (
    "serviceWorker" in navigator &&
    (window.isSecureContext || LOCAL_SERVICE_WORKER_HOSTS.has(window.location.hostname))
  );
}

async function clearPrivateTripCaches(): Promise<void> {
  if (!("caches" in window)) return;
  const keys = await caches.keys();
  await Promise.all(
    keys
      .filter((key) => key.startsWith(PRIVATE_TRIP_CACHE_PREFIX))
      .map((key) => caches.delete(key)),
  );
}

function wirePrivateCacheCleanup(): void {
  const body = document.body;
  if (!body) return;

  if (body.dataset.accountAuthenticated !== "true") {
    void clearPrivateTripCaches();
  }

  document
    .querySelectorAll<HTMLFormElement>("[data-pwa-private-clear-on-submit]")
    .forEach((form) => {
      if (form.dataset.pwaPrivateCleanupWired === "true") return;
      form.dataset.pwaPrivateCleanupWired = "true";
      form.addEventListener("submit", (event) => {
        if (form.dataset.pwaPrivateCleanupReady === "true") return;
        event.preventDefault();
        void clearPrivateTripCaches().finally(() => {
          form.dataset.pwaPrivateCleanupReady = "true";
          form.submit();
        });
      });
    });
}

function registerServiceWorker(): void {
  if (!serviceWorkerEligible()) return;

  const serviceWorkerUrl = document.body?.dataset.pwaServiceWorkerUrl;
  if (!serviceWorkerUrl) return;

  void navigator.serviceWorker.register(serviceWorkerUrl, { scope: "/" }).catch(() => {
    // PWA support is optional enhancement. A registration failure must never
    // interrupt conversion, saved-state or accessibility behavior.
  });
}

window.addEventListener(
  "load",
  () => {
    // Keep installability outside the hard initial-render request budget.
    window.setTimeout(registerServiceWorker, 2500);
  },
  { once: true },
);


wirePrivateCacheCleanup();
