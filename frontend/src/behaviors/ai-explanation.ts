const DEFAULT_REGION_ID = "conversion-explanation-region";
const DEFAULT_CLIENT_STATUS_ID = "explanation-client-status";
const DEFAULT_ANNOUNCER_ID = "explanation-announcer";
const TRIGGER_SELECTOR = "[data-ai-explanation-trigger]";
const FOCUS_SELECTOR = "[data-ai-explanation-focus]";

interface ExplanationTargets {
  region: HTMLElement | null;
  clientStatus: HTMLElement | null;
  announcer: HTMLElement | null;
}

function explanationTrigger(target: EventTarget | null): HTMLElement | null {
  return target instanceof Element ? target.closest<HTMLElement>(TRIGGER_SELECTOR) : null;
}

function elementById(id: string | undefined, fallback: string): HTMLElement | null {
  return document.getElementById(id?.trim() || fallback);
}

function targetsForTrigger(trigger: HTMLElement): ExplanationTargets {
  return {
    region: elementById(trigger.dataset.aiExplanationRegion, DEFAULT_REGION_ID),
    clientStatus: elementById(trigger.dataset.aiClientStatus, DEFAULT_CLIENT_STATUS_ID),
    announcer: elementById(trigger.dataset.aiAnnouncer, DEFAULT_ANNOUNCER_ID),
  };
}

function targetsForRegion(region: HTMLElement): ExplanationTargets {
  return {
    region,
    clientStatus: elementById(region.dataset.aiClientStatus, DEFAULT_CLIENT_STATUS_ID),
    announcer: elementById(region.dataset.aiAnnouncer, DEFAULT_ANNOUNCER_ID),
  };
}

function setPending(region: HTMLElement | null, delta: number): void {
  if (!region) return;

  const current = Number.parseInt(region.dataset.aiPendingRequests ?? "0", 10);
  const next = Math.max(0, (Number.isFinite(current) ? current : 0) + delta);
  region.dataset.aiPendingRequests = String(next);
  region.setAttribute("aria-busy", next > 0 ? "true" : "false");
}

function resetPending(region: HTMLElement | null): void {
  if (!region) return;
  region.dataset.aiPendingRequests = "0";
  region.setAttribute("aria-busy", "false");
}

function announce(announcer: HTMLElement | null, message: string): void {
  if (!announcer) return;

  announcer.textContent = "";
  window.setTimeout(() => {
    announcer.textContent = message;
  }, 0);
}

function clearClientStatus(status: HTMLElement | null): void {
  if (status) status.textContent = "";
}

function showClientFailure(trigger: HTMLElement): void {
  const targets = targetsForTrigger(trigger);
  resetPending(targets.region);
  const status = targets.clientStatus;
  if (!status) return;

  status.textContent =
    "The explanation request could not be completed. Choose the question again to retry.";
  announce(targets.announcer, "Explanation request failed. Choose the question again to retry.");
  status.focus();
}

document.addEventListener("htmx:beforeRequest", (event) => {
  const trigger = explanationTrigger(event.target);
  if (!trigger) return;

  const targets = targetsForTrigger(trigger);
  clearClientStatus(targets.clientStatus);
  setPending(targets.region, 1);
  const label = trigger.dataset.aiExplanationLabel ?? trigger.textContent?.trim();
  announce(
    targets.announcer,
    label ? `Generating explanation: ${label}` : "Generating explanation.",
  );
});

document.addEventListener("htmx:afterRequest", (event) => {
  const trigger = explanationTrigger(event.target);
  if (!trigger) return;
  setPending(targetsForTrigger(trigger).region, -1);
});

document.addEventListener("htmx:afterSwap", (event) => {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;

  const isExplanationRegion =
    target.id === DEFAULT_REGION_ID || target.hasAttribute("data-ai-pending-requests");
  if (!isExplanationRegion) return;

  const targets = targetsForRegion(target);
  resetPending(targets.region);
  clearClientStatus(targets.clientStatus);

  const focusTarget = target.querySelector<HTMLElement>(FOCUS_SELECTOR);
  const generated = target.querySelector<HTMLElement>("[data-ai-generated]")?.dataset.aiGenerated;
  if (generated === "true") {
    announce(targets.announcer, "AI explanation ready.");
  } else if (generated === "false") {
    announce(targets.announcer, "Built-in explanation ready. Live AI is unavailable.");
  } else if (target.querySelector('[role="alert"]')) {
    announce(targets.announcer, "Explanation unavailable. Choose the question again to retry.");
  }

  focusTarget?.focus();
});

document.addEventListener("htmx:responseError", (event) => {
  const trigger = explanationTrigger(event.target);
  if (trigger) showClientFailure(trigger);
});

document.addEventListener("htmx:sendError", (event) => {
  const trigger = explanationTrigger(event.target);
  if (trigger) showClientFailure(trigger);
});

document.addEventListener("htmx:timeout", (event) => {
  const trigger = explanationTrigger(event.target);
  if (trigger) showClientFailure(trigger);
});

export {};
