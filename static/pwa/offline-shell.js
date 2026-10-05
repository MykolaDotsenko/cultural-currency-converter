(() => {
  "use strict";

  const STORAGE_KEY = "cultural-currency.offline-trips.v1";
  const PRIVATE_TRIP_CACHE = "cultural-currency-private-trip-v1";
  const section = document.querySelector("[data-offline-trip-list]");
  const items = document.querySelector("[data-offline-trip-items]");
  if (!(section instanceof HTMLElement) || !(items instanceof HTMLElement)) return;

  async function renderStoredTrips() {
    let parsed;
    try {
      parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "[]");
    } catch {
      return;
    }
    if (!Array.isArray(parsed) || !("caches" in window)) return;

    const candidates = parsed
      .filter((item) => item && typeof item === "object")
      .map((item) => ({
        scenarioId: String(item.scenarioId || ""),
        snapshotUrl: String(item.snapshotUrl || ""),
        detailUrl: String(item.detailUrl || ""),
        destination: String(item.destination || "Saved trip").slice(0, 120),
        generatedAt: String(item.generatedAt || ""),
      }))
      .filter(
        (item) =>
          /^\d+$/.test(item.scenarioId) &&
          item.snapshotUrl === `/saved/scenarios/${item.scenarioId}/offline-snapshot/` &&
          item.detailUrl === `/saved/scenarios/${item.scenarioId}/` &&
          Number.isFinite(Date.parse(item.generatedAt)),
      )
      .slice(0, 8);

    const cache = await caches.open(PRIVATE_TRIP_CACHE);
    const available = [];
    for (const item of candidates) {
      const absoluteSnapshotUrl = new URL(item.snapshotUrl, window.location.origin).toString();
      if (await cache.match(absoluteSnapshotUrl)) available.push(item);
    }
    if (available.length === 0) return;

    for (const item of available) {
      const link = document.createElement("a");
      link.className = "offline-trip-link";
      link.href = item.detailUrl;

      const label = document.createElement("strong");
      label.textContent = item.destination || "Saved trip";
      const meta = document.createElement("span");
      meta.textContent = "Stored offline snapshot · never live";

      link.append(label, meta);
      items.append(link);
    }
    section.hidden = false;
  }

  void renderStoredTrips();
})();
