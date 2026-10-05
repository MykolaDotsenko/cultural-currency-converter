const LOCAL_SERVICE_WORKER_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);
const PRIVATE_TRIP_CACHE = "cultural-currency-private-trip-v1";
const OFFLINE_TRIP_STORAGE_KEY = "cultural-currency.offline-trips.v1";

function purgePrivateOfflineDataWhenAnonymous(): void {
  if (document.body?.dataset.accountAuthenticated === "true") return;

  try {
    window.localStorage.removeItem(OFFLINE_TRIP_STORAGE_KEY);
  } catch {
    // Storage can be unavailable in hardened/private browser modes.
  }

  if ("caches" in window) {
    void window.caches.delete(PRIVATE_TRIP_CACHE).catch(() => {
      // Optional cleanup failure must not affect converter behavior.
    });
  }
}

function serviceWorkerEligible(): boolean {
  return (
    "serviceWorker" in navigator &&
    (window.isSecureContext || LOCAL_SERVICE_WORKER_HOSTS.has(window.location.hostname))
  );
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

purgePrivateOfflineDataWhenAnonymous();

window.addEventListener(
  "load",
  () => {
    // Keep installability outside the hard initial-render request budget.
    window.setTimeout(registerServiceWorker, 2500);
  },
  { once: true },
);
