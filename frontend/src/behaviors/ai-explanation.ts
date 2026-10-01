const REGION_ID = "conversion-explanation-region";
const CLIENT_STATUS_ID = "explanation-client-status";
const TRIGGER_SELECTOR = "[data-ai-explanation-trigger]";
const FOCUS_SELECTOR = "[data-ai-explanation-focus]";

function explanationRegion(): HTMLElement | null {
  return document.getElementById(REGION_ID);
}

function clientStatus(): HTMLElement | null {
  return document.getElementById(CLIENT_STATUS_ID);
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
  status.focus();
}

document.addEventListener("htmx:beforeRequest", (event) => {
  if (!explanationTrigger(event.target)) return;
  clearClientStatus();
  setPending(1);
});

document.addEventListener("htmx:afterRequest", (event) => {
  if (!explanationTrigger(event.target)) return;
  setPending(-1);
});

document.addEventListener("htmx:afterSwap", (event) => {
  const target = event.target;
  if (!(target instanceof Element) || target.id !== REGION_ID) return;

  resetPending();
  target.querySelector<HTMLElement>(FOCUS_SELECTOR)?.focus();
});

document.addEventListener("htmx:responseError", (event) => {
  if (!explanationTrigger(event.target)) return;
  showClientFailure();
});

document.addEventListener("htmx:sendError", (event) => {
  if (!explanationTrigger(event.target)) return;
  showClientFailure();
});
