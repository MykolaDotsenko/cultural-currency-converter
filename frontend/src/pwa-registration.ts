const LOCAL_SERVICE_WORKER_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]"]);

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

window.addEventListener(
  "load",
  () => {
    // Keep installability outside the hard initial-render request budget.
    window.setTimeout(registerServiceWorker, 2500);
  },
  { once: true },
);
