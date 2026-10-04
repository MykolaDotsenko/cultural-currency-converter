const PRIVATE_TRIP_CACHE = "cultural-currency-private-trip-v1";

type OfflineTripSurface = HTMLElement & {
  dataset: DOMStringMap & {
    snapshotUrl?: string;
    offlineUrl?: string;
    currentRevision?: string;
    packVersion?: string;
  };
};

interface CachedSnapshot {
  response: Response;
  revision: string;
  generatedAt: string;
  contextAsOf: string;
  version: string;
}

function cacheStorageAvailable(): boolean {
  return "caches" in window && window.isSecureContext;
}

function absoluteUrl(path: string): string {
  return new URL(path, window.location.origin).toString();
}

async function cachedSnapshot(surface: OfflineTripSurface): Promise<CachedSnapshot | null> {
  const offlineUrl = surface.dataset.offlineUrl;
  if (!offlineUrl || !cacheStorageAvailable()) return null;

  const cache = await caches.open(PRIVATE_TRIP_CACHE);
  const response = await cache.match(absoluteUrl(offlineUrl));
  if (!response) return null;

  return {
    response,
    revision: response.headers.get("X-PWA-Offline-Revision") ?? "",
    generatedAt: response.headers.get("X-PWA-Offline-Generated-At") ?? "",
    contextAsOf: response.headers.get("X-PWA-Offline-Context-As-Of") ?? "",
    version: response.headers.get("X-PWA-Offline-Snapshot-Version") ?? "",
  };
}

function readableTimestamp(raw: string): string {
  if (!raw) return "unknown time";
  const value = new Date(raw);
  if (Number.isNaN(value.getTime())) return raw;
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(value);
}

function setBusy(surface: OfflineTripSurface, busy: boolean): void {
  surface
    .querySelectorAll<HTMLButtonElement>("[data-offline-trip-save], [data-offline-trip-remove]")
    .forEach((button) => {
      button.disabled = busy;
    });
}

async function renderSurfaceState(surface: OfflineTripSurface): Promise<void> {
  const status = surface.querySelector<HTMLElement>("[data-offline-trip-status]");
  const save = surface.querySelector<HTMLButtonElement>("[data-offline-trip-save]");
  const open = surface.querySelector<HTMLAnchorElement>("[data-offline-trip-open]");
  const remove = surface.querySelector<HTMLButtonElement>("[data-offline-trip-remove]");
  if (!status || !save || !open || !remove) return;

  if (!cacheStorageAvailable()) {
    surface.hidden = true;
    return;
  }

  surface.hidden = false;
  const cached = await cachedSnapshot(surface);
  if (!cached) {
    status.textContent =
      "Not stored on this device. The portable download remains available without PWA storage.";
    save.textContent = "Make available offline";
    open.hidden = true;
    remove.hidden = true;
    return;
  }

  open.hidden = false;
  remove.hidden = false;
  const currentRevision = surface.dataset.currentRevision ?? "";
  const currentVersion = surface.dataset.packVersion ?? "";
  const current = cached.revision === currentRevision && cached.version === currentVersion;
  if (current) {
    status.textContent =
      `Available offline · generated ${readableTimestamp(cached.generatedAt)} · context as of ${cached.contextAsOf || "unknown date"} · stored, not live.`;
    save.textContent = "Replace offline copy";
  } else {
    status.textContent =
      "Offline copy is outdated because this saved trip changed. Replace it before relying on the stored budget.";
    save.textContent = "Replace outdated copy";
  }
}

async function saveSnapshot(surface: OfflineTripSurface): Promise<void> {
  const snapshotUrl = surface.dataset.snapshotUrl;
  const offlineUrl = surface.dataset.offlineUrl;
  const status = surface.querySelector<HTMLElement>("[data-offline-trip-status]");
  if (!snapshotUrl || !offlineUrl || !status || !cacheStorageAvailable()) return;

  setBusy(surface, true);
  status.textContent = "Preparing a stored-only offline copy…";
  try {
    const response = await fetch(snapshotUrl, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { "X-Requested-With": "PWA offline snapshot" },
    });
    if (!response.ok || response.headers.get("X-PWA-Offline-Snapshot") !== "1") {
      throw new Error("Offline snapshot response was not valid.");
    }

    const headers = new Headers(response.headers);
    headers.delete("Vary");
    headers.delete("Content-Disposition");
    const storedResponse = new Response(await response.text(), {
      status: 200,
      statusText: "OK",
      headers,
    });

    const cache = await caches.open(PRIVATE_TRIP_CACHE);
    await cache.put(absoluteUrl(offlineUrl), storedResponse);
    await renderSurfaceState(surface);
  } catch {
    status.textContent =
      "Could not update the offline copy. Your saved scenario and downloadable pack were not changed.";
  } finally {
    setBusy(surface, false);
  }
}

async function removeSnapshot(surface: OfflineTripSurface): Promise<void> {
  const offlineUrl = surface.dataset.offlineUrl;
  const status = surface.querySelector<HTMLElement>("[data-offline-trip-status]");
  if (!offlineUrl || !status || !cacheStorageAvailable()) return;

  setBusy(surface, true);
  try {
    const cache = await caches.open(PRIVATE_TRIP_CACHE);
    await cache.delete(absoluteUrl(offlineUrl));
    await renderSurfaceState(surface);
    status.textContent = "Offline copy removed from this browser profile.";
  } finally {
    setBusy(surface, false);
  }
}

function wireScenarioDelete(surface: OfflineTripSurface): void {
  const offlineUrl = surface.dataset.offlineUrl;
  if (!offlineUrl || !cacheStorageAvailable()) return;

  document.querySelectorAll<HTMLFormElement>("[data-offline-trip-delete-form]").forEach((form) => {
    if (form.dataset.offlineCleanupWired === "true") return;
    form.dataset.offlineCleanupWired = "true";
    form.addEventListener("submit", (event) => {
      if (form.dataset.offlineCleanupReady === "true") return;
      event.preventDefault();
      void caches
        .open(PRIVATE_TRIP_CACHE)
        .then((cache) => cache.delete(absoluteUrl(offlineUrl)))
        .finally(() => {
          form.dataset.offlineCleanupReady = "true";
          form.submit();
        });
    });
  });
}

function wireSurface(surface: OfflineTripSurface): void {
  if (surface.dataset.offlineTripWired === "true") return;
  surface.dataset.offlineTripWired = "true";

  surface.querySelector<HTMLButtonElement>("[data-offline-trip-save]")?.addEventListener("click", () => {
    void saveSnapshot(surface);
  });
  surface
    .querySelector<HTMLButtonElement>("[data-offline-trip-remove]")
    ?.addEventListener("click", () => {
      void removeSnapshot(surface);
    });
  wireScenarioDelete(surface);
  void renderSurfaceState(surface);
}

export function enhancePwaOfflineTrip(): void {
  document.querySelectorAll<OfflineTripSurface>("[data-offline-trip-controls]").forEach(wireSurface);
}
