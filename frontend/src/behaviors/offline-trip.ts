const PRIVATE_TRIP_CACHE = "cultural-currency-private-trip-v1";
const OFFLINE_TRIP_STORAGE_KEY = "cultural-currency.offline-trips.v1";
const REFRESH_RECOMMENDED_AFTER_MS = 24 * 60 * 60 * 1000;
const MAX_OFFLINE_TRIPS = 8;

type OfflineTripMetadata = {
  scenarioId: string;
  snapshotUrl: string;
  detailUrl: string;
  destination: string;
  revision: string;
  generatedAt: string;
};

type OfflineTripControl = {
  scenarioId: string;
  snapshotUrl: string;
  detailUrl: string;
  destination: string;
  revision: string;
  status: HTMLElement;
  saveButton: HTMLButtonElement;
  removeButton: HTMLButtonElement;
};

function safeStorage(): Storage | null {
  try {
    const storage = window.localStorage;
    const probeKey = `${OFFLINE_TRIP_STORAGE_KEY}.probe`;
    storage.setItem(probeKey, "1");
    storage.removeItem(probeKey);
    return storage;
  } catch {
    return null;
  }
}

function isSnapshotUrl(value: string, scenarioId: string): boolean {
  return value === `/saved/scenarios/${scenarioId}/offline-snapshot/`;
}

function isDetailUrl(value: string, scenarioId: string): boolean {
  return value === `/saved/scenarios/${scenarioId}/`;
}

function loadMetadata(storage: Storage): OfflineTripMetadata[] {
  try {
    const parsed: unknown = JSON.parse(storage.getItem(OFFLINE_TRIP_STORAGE_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];

    return parsed
      .filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === "object")
      .map((item) => ({
        scenarioId: String(item.scenarioId ?? ""),
        snapshotUrl: String(item.snapshotUrl ?? ""),
        detailUrl: String(item.detailUrl ?? ""),
        destination: String(item.destination ?? "").slice(0, 120),
        revision: String(item.revision ?? ""),
        generatedAt: String(item.generatedAt ?? ""),
      }))
      .filter(
        (item) =>
          /^\d+$/.test(item.scenarioId) &&
          isSnapshotUrl(item.snapshotUrl, item.scenarioId) &&
          isDetailUrl(item.detailUrl, item.scenarioId) &&
          item.revision.length <= 64 &&
          Number.isFinite(Date.parse(item.generatedAt)),
      )
      .slice(0, MAX_OFFLINE_TRIPS);
  } catch {
    return [];
  }
}

function saveMetadata(storage: Storage, items: OfflineTripMetadata[]): void {
  storage.setItem(OFFLINE_TRIP_STORAGE_KEY, JSON.stringify(items.slice(0, MAX_OFFLINE_TRIPS)));
}

async function ensureServiceWorkerReady(): Promise<boolean> {
  if (!("serviceWorker" in navigator)) return false;
  const serviceWorkerUrl = document.body?.dataset.pwaServiceWorkerUrl;
  if (!serviceWorkerUrl) return false;

  try {
    await navigator.serviceWorker.register(serviceWorkerUrl, { scope: "/" });
    await navigator.serviceWorker.ready;
    if (navigator.serviceWorker.controller) return true;

    return await new Promise<boolean>((resolve) => {
      const timer = window.setTimeout(() => resolve(false), 3000);
      navigator.serviceWorker.addEventListener(
        "controllerchange",
        () => {
          window.clearTimeout(timer);
          resolve(Boolean(navigator.serviceWorker.controller));
        },
        { once: true },
      );
    });
  } catch {
    return false;
  }
}

async function deleteCachedSnapshot(cache: Cache, snapshotUrl: string): Promise<void> {
  const absoluteUrl = new URL(snapshotUrl, window.location.origin).toString();
  await cache.delete(absoluteUrl);
}

function updateStatus(control: OfflineTripControl, message: string, tone: string): void {
  control.status.textContent = message;
  control.status.dataset.storageTone = tone;
}

function setButtons(control: OfflineTripControl, saved: boolean, refresh: boolean): void {
  control.saveButton.hidden = false;
  control.saveButton.textContent = refresh ? "Refresh offline copy" : "Save trip for offline";
  control.removeButton.hidden = !saved;
}

async function cachedSnapshotExists(snapshotUrl: string): Promise<boolean> {
  const cache = await caches.open(PRIVATE_TRIP_CACHE);
  const absoluteUrl = new URL(snapshotUrl, window.location.origin).toString();
  return (await cache.match(absoluteUrl)) !== undefined;
}

function snapshotAgeNeedsRefresh(generatedAt: string): boolean {
  const ageMs = Date.now() - Date.parse(generatedAt);
  return Number.isFinite(ageMs) && ageMs >= REFRESH_RECOMMENDED_AFTER_MS;
}

async function refreshControlState(control: OfflineTripControl, storage: Storage): Promise<void> {
  const metadata = loadMetadata(storage).find((item) => item.scenarioId === control.scenarioId);
  if (!metadata || !(await cachedSnapshotExists(control.snapshotUrl))) {
    if (metadata) {
      saveMetadata(
        storage,
        loadMetadata(storage).filter((item) => item.scenarioId !== control.scenarioId),
      );
    }
    setButtons(control, false, false);
    updateStatus(
      control,
      "Not saved in the installed app on this device. The portable HTML pack remains separate.",
      "neutral",
    );
    return;
  }

  if (metadata.revision !== control.revision) {
    setButtons(control, true, true);
    updateStatus(
      control,
      "Offline copy is out of date because this saved trip changed. Refresh it before relying on the snapshot.",
      "warning",
    );
    return;
  }

  const aged = snapshotAgeNeedsRefresh(metadata.generatedAt);
  setButtons(control, true, aged);
  updateStatus(
    control,
    aged
      ? "Saved for offline on this device, but this stored snapshot is more than 24 hours old. Refresh recommended."
      : "Saved for offline on this device. Stored snapshot, never live.",
    aged ? "warning" : "feedback",
  );
}

async function saveSnapshot(control: OfflineTripControl, storage: Storage): Promise<void> {
  control.saveButton.disabled = true;
  control.removeButton.disabled = true;
  updateStatus(control, "Saving a private offline snapshot on this device…", "feedback");

  try {
    const response = await fetch(control.snapshotUrl, {
      credentials: "same-origin",
      headers: { Accept: "text/html" },
    });
    if (!response.ok) throw new Error("snapshot request failed");
    if (!response.headers.get("content-type")?.startsWith("text/html")) {
      throw new Error("snapshot response is not HTML");
    }
    if (response.headers.get("x-cultural-currency-offline-snapshot") !== "1") {
      throw new Error("snapshot response is missing its contract header");
    }

    const revision = response.headers.get("x-cultural-currency-snapshot-revision") ?? "";
    const generatedAt = response.headers.get("x-cultural-currency-snapshot-generated-at") ?? "";
    if (revision !== control.revision) throw new Error("scenario changed during snapshot creation");
    if (!Number.isFinite(Date.parse(generatedAt))) throw new Error("invalid generation timestamp");

    const cache = await caches.open(PRIVATE_TRIP_CACHE);
    const absoluteUrl = new URL(control.snapshotUrl, window.location.origin).toString();
    await cache.put(absoluteUrl, response.clone());

    const metadata: OfflineTripMetadata = {
      scenarioId: control.scenarioId,
      snapshotUrl: control.snapshotUrl,
      detailUrl: control.detailUrl,
      destination: control.destination,
      revision,
      generatedAt,
    };
    const others = loadMetadata(storage).filter((item) => item.scenarioId !== control.scenarioId);
    const nextItems = [metadata, ...others];
    const evicted = nextItems.slice(MAX_OFFLINE_TRIPS);
    try {
      saveMetadata(storage, nextItems);
    } catch {
      await deleteCachedSnapshot(cache, control.snapshotUrl);
      throw new Error("offline trip metadata could not be persisted");
    }
    for (const item of evicted) {
      await deleteCachedSnapshot(cache, item.snapshotUrl);
    }
    await refreshControlState(control, storage);
  } catch {
    updateStatus(
      control,
      "Could not save the offline app copy. Your online scenario was not changed; use the portable HTML pack if needed.",
      "warning",
    );
  } finally {
    control.saveButton.disabled = false;
    control.removeButton.disabled = false;
  }
}

async function purgeScenarioSnapshot(
  control: OfflineTripControl,
  storage: Storage,
): Promise<void> {
  let failed = false;

  try {
    const cache = await caches.open(PRIVATE_TRIP_CACHE);
    await deleteCachedSnapshot(cache, control.snapshotUrl);
  } catch {
    failed = true;
  }

  try {
    saveMetadata(
      storage,
      loadMetadata(storage).filter((item) => item.scenarioId !== control.scenarioId),
    );
  } catch {
    failed = true;
  }

  if (failed) throw new Error("offline scenario cleanup was incomplete");
}

async function removeSnapshot(control: OfflineTripControl, storage: Storage): Promise<void> {
  control.saveButton.disabled = true;
  control.removeButton.disabled = true;
  try {
    await purgeScenarioSnapshot(control, storage);
    setButtons(control, false, false);
    updateStatus(control, "Offline app copy removed from this device.", "feedback");
  } catch {
    updateStatus(
      control,
      "Could not remove the offline copy from browser storage. Try again before sharing this device.",
      "warning",
    );
  } finally {
    control.saveButton.disabled = false;
    control.removeButton.disabled = false;
  }
}

function scenarioDeleteForm(control: OfflineTripControl): HTMLFormElement | null {
  const expectedPath = `${control.detailUrl}delete/`;
  for (const form of document.querySelectorAll<HTMLFormElement>("form[method='post']")) {
    try {
      const action = new URL(form.action, window.location.origin);
      if (action.origin === window.location.origin && action.pathname === expectedPath) return form;
    } catch {
      // Ignore malformed unrelated form actions.
    }
  }
  return null;
}

function bindScenarioDeleteCleanup(control: OfflineTripControl, storage: Storage): void {
  const form = scenarioDeleteForm(control);
  if (!form || form.dataset.offlineTripDeleteCleanup === "true") return;
  form.dataset.offlineTripDeleteCleanup = "true";

  form.addEventListener("submit", (event) => {
    if (form.dataset.offlineTripDeleteSubmitting === "true") return;

    event.preventDefault();
    form.dataset.offlineTripDeleteSubmitting = "true";
    const submitter =
      event.submitter instanceof HTMLButtonElement
        ? event.submitter
        : form.querySelector<HTMLButtonElement>('button[type="submit"]');
    if (submitter) submitter.disabled = true;

    void purgeScenarioSnapshot(control, storage)
      .catch(() => {
        // Browser storage is best-effort. A cleanup failure must never block
        // the explicit server-side scenario deletion requested by the user.
      })
      .finally(() => {
        form.submit();
      });
  });
}

function parseControl(root: HTMLElement): OfflineTripControl | null {
  const scenarioId = root.dataset.offlineTripScenarioId ?? "";
  const snapshotUrl = root.dataset.offlineTripSnapshotUrl ?? "";
  const detailUrl = root.dataset.offlineTripDetailUrl ?? "";
  const destination = (root.dataset.offlineTripDestination ?? "Saved trip").slice(0, 120);
  const revision = root.dataset.offlineTripRevision ?? "";
  const status = root.querySelector<HTMLElement>("[data-offline-trip-status]");
  const saveButton = root.querySelector<HTMLButtonElement>("[data-offline-trip-save]");
  const removeButton = root.querySelector<HTMLButtonElement>("[data-offline-trip-remove]");

  if (
    !/^\d+$/.test(scenarioId) ||
    !isSnapshotUrl(snapshotUrl, scenarioId) ||
    !isDetailUrl(detailUrl, scenarioId) ||
    !revision ||
    !status ||
    !saveButton ||
    !removeButton
  ) {
    return null;
  }

  return {
    scenarioId,
    snapshotUrl,
    detailUrl,
    destination,
    revision,
    status,
    saveButton,
    removeButton,
  };
}

export function enhanceOfflineTripControls(): void {
  const storage = safeStorage();
  const cacheSupported = "caches" in window;
  const serviceWorkerSupported = "serviceWorker" in navigator;

  for (const root of document.querySelectorAll<HTMLElement>("[data-offline-trip-control]")) {
    if (root.dataset.offlineTripEnhanced === "true") continue;
    root.dataset.offlineTripEnhanced = "true";

    const control = parseControl(root);
    if (!control) continue;

    if (!storage || !cacheSupported || !serviceWorkerSupported) {
      updateStatus(
        control,
        "This browser cannot keep an app snapshot. Use the portable HTML pack instead.",
        "warning",
      );
      continue;
    }

    control.saveButton.addEventListener("click", () => {
      void saveSnapshot(control, storage);
    });
    control.removeButton.addEventListener("click", () => {
      void removeSnapshot(control, storage);
    });
    bindScenarioDeleteCleanup(control, storage);

    updateStatus(control, "Preparing offline app storage…", "neutral");
    void ensureServiceWorkerReady().then((ready) => {
      if (ready) {
        void refreshControlState(control, storage);
        return;
      }
      updateStatus(
        control,
        "Offline app storage could not start. Use the portable HTML pack instead.",
        "warning",
      );
    });
  }
}
