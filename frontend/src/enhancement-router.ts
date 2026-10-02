type EnhancementRoot = Document | Element;

let currentConverterModule: Promise<typeof import("./behaviors/current-converter")> | null = null;
let pickerModule: Promise<typeof import("./behaviors/picker")> | null = null;
let aiExplanationModule: Promise<typeof import("./behaviors/ai-explanation")> | null = null;
let localSavedStateModule: Promise<typeof import("./behaviors/local-saved-state")> | null = null;
let rateChartLoaderModule: Promise<typeof import("./behaviors/rate-chart-loader")> | null = null;

function contains(root: EnhancementRoot, selector: string): boolean {
  if (root instanceof Element && root.matches(selector)) return true;
  return root.querySelector(selector) !== null;
}

function reportEnhancementFailure(label: string, error: unknown): void {
  console.error(`${label} enhancement failed to load.`, error);
}

function loadCurrentConverter(root: EnhancementRoot): void {
  const hasPicker = contains(root, "[data-picker-dialog]");
  const hasCurrentForm = contains(root, "[data-current-conversion-form]");
  if (!hasPicker && !hasCurrentForm) return;

  currentConverterModule ??= import("./behaviors/current-converter");

  if (hasPicker) {
    pickerModule ??= import("./behaviors/picker");
    void Promise.all([currentConverterModule, pickerModule])
      .then(([currentConverter, picker]) => {
        currentConverter.enhanceCurrentConverterBehavior();
        picker.enhanceCurrentConverter();
      })
      .catch((error: unknown) => reportEnhancementFailure("Converter picker", error));
    return;
  }

  void currentConverterModule
    .then((module) => module.enhanceCurrentConverterBehavior())
    .catch((error: unknown) => reportEnhancementFailure("Current converter", error));
}

function loadAiExplanation(root: EnhancementRoot): void {
  if (
    !contains(
      root,
      "[data-ai-explanation-trigger], #conversion-explanation-region, #explanation-client-status",
    )
  ) {
    return;
  }

  aiExplanationModule ??= import("./behaviors/ai-explanation");
  void aiExplanationModule.catch((error: unknown) =>
    reportEnhancementFailure("AI explanation", error),
  );
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

function loadRateCharts(root: EnhancementRoot): void {
  if (!contains(root, "[data-rate-chart]")) return;

  rateChartLoaderModule ??= import("./behaviors/rate-chart-loader");
  void rateChartLoaderModule.catch((error: unknown) =>
    reportEnhancementFailure("Rate chart", error),
  );
}

export function loadEnhancements(root: EnhancementRoot = document): void {
  loadCurrentConverter(root);
  loadAiExplanation(root);
  loadLocalSavedState(root);
  loadRateCharts(root);
}

loadEnhancements();

document.addEventListener("htmx:afterSwap", (event) => {
  const detail = (event as CustomEvent<{ target?: Element }>).detail;
  const target = detail?.target ?? (event.target instanceof Element ? event.target : document);
  loadEnhancements(target);
});
