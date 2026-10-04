type EnhancementRoot = Document | Element;

let converterEnhancementsModule: Promise<
  typeof import("./behaviors/converter-enhancements")
> | null = null;
let localSavedStateModule: Promise<typeof import("./behaviors/local-saved-state")> | null = null;
let pwaOfflineTripModule: Promise<typeof import("./behaviors/pwa-offline-trip")> | null = null;
let rateChartModule: Promise<typeof import("./behaviors/rate-chart")> | null = null;

function contains(root: EnhancementRoot, selector: string): boolean {
  if (root instanceof Element && root.matches(selector)) return true;
  return root.querySelector(selector) !== null;
}

function reportEnhancementFailure(label: string, error: unknown): void {
  console.error(`${label} enhancement failed to load.`, error);
}

function loadCurrentConverter(root: EnhancementRoot): void {
  if (!contains(root, "[data-picker-dialog], [data-current-conversion-form]")) return;

  converterEnhancementsModule ??= import("./behaviors/converter-enhancements");
  void converterEnhancementsModule
    .then((module) => module.enhanceConverterSurface())
    .catch((error: unknown) => reportEnhancementFailure("Converter", error));
}

function loadLocalSavedState(root: EnhancementRoot): void {
  const needsLocalState =
    document.body?.dataset.accountAuthenticated === "true" ||
    contains(
      root,
      "[data-local-conversion-snapshot], [data-local-saved-place], [data-local-saved-state-page]",
    );
  if (!needsLocalState) return;

  localSavedStateModule ??= import("./behaviors/local-saved-state");
  void localSavedStateModule
    .then((module) => module.enhanceLocalSavedState())
    .catch((error: unknown) => reportEnhancementFailure("Saved state", error));
}

function loadPwaOfflineTrip(root: EnhancementRoot): void {
  if (!contains(root, "[data-offline-trip-controls]")) return;

  pwaOfflineTripModule ??= import("./behaviors/pwa-offline-trip");
  void pwaOfflineTripModule
    .then((module) => module.enhancePwaOfflineTrip())
    .catch((error: unknown) => reportEnhancementFailure("Offline trip", error));
}

function loadRateCharts(root: EnhancementRoot): void {
  if (!contains(root, "[data-rate-chart]")) return;

  rateChartModule ??= import("./behaviors/rate-chart");
  void rateChartModule
    .then((module) => module.enhanceRateCharts(document))
    .catch((error: unknown) => reportEnhancementFailure("Rate chart", error));
}

export function loadEnhancements(root: EnhancementRoot = document): void {
  loadCurrentConverter(root);
  loadLocalSavedState(root);
  loadPwaOfflineTrip(root);
  loadRateCharts(root);
}

loadEnhancements();

document.addEventListener("htmx:afterSwap", () => {
  // HTMX event targets may refer to the triggering/swapped element rather than
  // every newly rendered progressive fragment. A document-level marker scan is
  // cheap and keeps demand-loaded enhancement discovery deterministic.
  loadEnhancements(document);
});

document.addEventListener("htmx:beforeCleanupElement", (event) => {
  if (!rateChartModule) return;

  const detail = (event as CustomEvent<{ elt?: Element }>).detail;
  const target = detail?.elt ?? (event.target instanceof Element ? event.target : null);
  if (!target) return;

  void rateChartModule.then((module) => module.destroyRateCharts(target));
});
