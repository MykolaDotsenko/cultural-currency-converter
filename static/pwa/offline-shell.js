(() => {
  "use strict";

  const STORAGE_KEY = "cultural-currency.offline-trips.v1";
  const section = document.querySelector("[data-offline-trip-list]");
  const items = document.querySelector("[data-offline-trip-items]");
  if (!(section instanceof HTMLElement) || !(items instanceof HTMLElement)) return;

  let parsed;
  try {
    parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "[]");
  } catch {
    return;
  }
  if (!Array.isArray(parsed)) return;

  const safe = parsed
    .filter((item) => item && typeof item === "object")
    .map((item) => ({
      scenarioId: String(item.scenarioId || ""),
      detailUrl: String(item.detailUrl || ""),
      destination: String(item.destination || "Saved trip").slice(0, 120),
      generatedAt: String(item.generatedAt || ""),
    }))
    .filter(
      (item) =>
        /^\d+$/.test(item.scenarioId) &&
        item.detailUrl === `/saved/scenarios/${item.scenarioId}/` &&
        Number.isFinite(Date.parse(item.generatedAt)),
    )
    .slice(0, 8);

  if (safe.length === 0) return;

  for (const item of safe) {
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
})();
