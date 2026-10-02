let chartModulePromise: Promise<typeof import("./rate-chart")> | null = null;

async function enhanceRateCharts(root: ParentNode = document): Promise<void> {
  if (!root.querySelector("[data-rate-chart]")) return;

  chartModulePromise ??= import("./rate-chart");
  const module = await chartModulePromise;
  module.enhanceRateCharts(root);
}

void enhanceRateCharts();

document.body.addEventListener("htmx:afterSwap", (event) => {
  const detail = (event as CustomEvent<{ target?: Element }>).detail;
  void enhanceRateCharts(detail?.target ?? document);
});

document.body.addEventListener("htmx:beforeCleanupElement", (event) => {
  if (!chartModulePromise) return;

  const detail = (event as CustomEvent<{ elt?: Element }>).detail;
  const target = detail?.elt ?? (event.target instanceof Element ? event.target : null);
  if (!target) return;

  void chartModulePromise.then((module) => {
    module.destroyRateCharts(target);
  });
});

export {};
