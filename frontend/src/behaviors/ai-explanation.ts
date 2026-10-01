const REGION_ID = "conversion-explanation-region";
const CLIENT_STATUS_ID = "explanation-client-status";
const ANNOUNCER_ID = "explanation-announcer";
const TRIGGER_SELECTOR = "[data-ai-explanation-trigger]";
const FOCUS_SELECTOR = "[data-ai-explanation-focus]";

function explanationRegion(): HTMLElement | null {
  return document.getElementById(REGION_ID);
}

function clientStatus(): HTMLElement | null {
  return document.getElementById(CLIENT_STATUS_ID);
}

function announcer(): HTMLElement | null {
  return document.getElementById(ANNOUNCER_ID);
}

function explanationTrigger(target: EventTarget | null): HTMLElement | null {
  return target instanceof Element ? target.closest<HTMLElement>(TRIGGER_SELECTOR) : null;
}

function setPending(delta: number): void {
  const region = explanationRegion();
  if (!region) return;

  const current = Number.parseInt(region.dataset.aiPendingRequests ?? "0", 10);
  const next = Math.max(0, (Number.isFinite(current) ? current : 0) + delta);
  region.dataset.aiPendingRequests = String(next);
  region.setAttribute("aria-busy", next > 0 ? "true" : "false");
}

function resetPending(): void {
  const region = explanationRegion();
  if (!region) return;
  region.dataset.aiPendingRequests = "0";
  region.setAttribute("aria-busy", "false");
}

function announce(message: string): void {
  const status = announcer();
  if (!status) return;

  status.textContent = "";
  window.setTimeout(() => {
    status.textContent = message;
  }, 0);
}

function clearClientStatus(): void {
  const status = clientStatus();
  if (status) status.textContent = "";
}

function showClientFailure(): void {
  resetPending();
  const status = clientStatus();
  if (!status) return;

  status.textContent =
    "The explanation request could not be completed. Choose the question again to retry.";
  announce("Explanation request failed. Choose the question again to retry.");
  status.focus();
}

document.addEventListener("htmx:beforeRequest", (event) => {
  if (!explanationTrigger(event.target)) return;
  clearClientStatus();
  setPending(1);
  const label = explanationTrigger(event.target)?.textContent?.trim();
  announce(label ? `Generating explanation: ${label}` : "Generating explanation.");
});

document.addEventListener("htmx:afterRequest", (event) => {
  if (!explanationTrigger(event.target)) return;
  setPending(-1);
});

document.addEventListener("htmx:afterSwap", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement) || target.id !== REGION_ID) return;

  resetPending();
  clearClientStatus();

  const focusTarget = target.querySelector<HTMLElement>(FOCUS_SELECTOR);
  const generated = target.querySelector<HTMLElement>("[data-ai-generated]")?.dataset.aiGenerated;
  if (generated === "true") {
    announce("AI explanation ready.");
  } else if (generated === "false") {
    announce("Built-in explanation ready. Live AI is unavailable.");
  } else if (target.querySelector('[role="alert"]')) {
    announce("Explanation unavailable. Choose the question again to retry.");
  }

  focusTarget?.focus();
});

document.addEventListener("htmx:responseError", (event) => {
  if (!explanationTrigger(event.target)) return;
  showClientFailure();
});

document.addEventListener("htmx:sendError", (event) => {
  if (!explanationTrigger(event.target)) return;
  showClientFailure();
});

document.addEventListener("htmx:timeout", (event) => {
  if (!explanationTrigger(event.target)) return;
  showClientFailure();
});
