let restoreFocusId: string | null = null;
let focusValidationSummaryAfterSwap = false;

export function requestFocusRestore(id: string): void {
  restoreFocusId = id;
}

function syncHistoricalDateField(form: HTMLFormElement): void {
  const field = form.querySelector<HTMLElement>("[data-historical-date-field]");
  const historical = form.querySelector<HTMLInputElement>(
    'input[name="rate_mode"][value="historical"]',
  );
  if (!field || !historical) return;

  field.hidden = !historical.checked;
}

function enhanceAutoRefresh(form: HTMLFormElement): void {
  syncHistoricalDateField(form);
  if (form.dataset.autoRefreshWired === "true") return;
  form.dataset.autoRefreshWired = "true";

  form.addEventListener("submit", (event) => {
    focusValidationSummaryAfterSwap = (event as SubmitEvent).submitter !== null;
  });

  let amountTimer: number | undefined;
  let dateTimer: number | undefined;

  form.addEventListener("input", (event) => {
    if (form.dataset.hasResult !== "true") return;
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;

    if (target.id === "id_amount") {
      window.clearTimeout(amountTimer);
      amountTimer = window.setTimeout(() => form.requestSubmit(), 400);
      return;
    }

    if (target.id === "id_requested_date") {
      const historical = form.querySelector<HTMLInputElement>(
        'input[name="rate_mode"][value="historical"]',
      );
      if (!historical?.checked || !target.value) return;

      window.clearTimeout(dateTimer);
      dateTimer = window.setTimeout(() => form.requestSubmit(), 80);
    }
  });

  form.addEventListener("change", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement || target instanceof HTMLSelectElement)) return;

    if (target.name === "destination_country") {
      const city = form.querySelector<HTMLInputElement>('input[name="destination_city_slug"]');
      if (city) city.value = "";
    }

    if (target.name === "rate_mode") {
      syncHistoricalDateField(form);
      if (form.dataset.hasResult !== "true") return;

      if (target.value === "historical") {
        const requestedDate = form.querySelector<HTMLInputElement>("#id_requested_date");
        if (!requestedDate?.value) {
          requestedDate?.focus();
          return;
        }
      }

      form.requestSubmit();
      return;
    }

    if (form.dataset.hasResult !== "true") return;
    if (target.type === "hidden" || target.id === "id_amount") return;

    if (target.id === "id_requested_date") {
      const historical = form.querySelector<HTMLInputElement>(
        'input[name="rate_mode"][value="historical"]',
      );
      if (!historical?.checked || !target.value) return;

      window.clearTimeout(dateTimer);
    }

    form.requestSubmit();
  });
}

function announceConversionResult(target: EventTarget | null, status: number | undefined): void {
  if (status !== 200 || !(target instanceof Element) || target.id !== "converter-panel") return;

  const announcer = document.getElementById("conversion-announcer");
  const payload = target.querySelector<HTMLElement>("[data-conversion-announcement]");
  const message = payload?.textContent?.trim();
  if (!announcer || !message) return;

  announcer.textContent = "";
  window.setTimeout(() => {
    announcer.textContent = message;
  }, 0);
}

function enhanceCurrentConverterBehavior(): void {
  const form = document.querySelector<HTMLFormElement>("[data-current-conversion-form]");
  if (form) enhanceAutoRefresh(form);
}

document.addEventListener("click", (event) => {
  const target = event.target;
  if (!(target instanceof Element)) return;
  const swap = target.closest<HTMLButtonElement>("#swap-contexts");
  if (swap) restoreFocusId = swap.id;
});

document.addEventListener("htmx:beforeRequest", (event) => {
  const target = event.target;
  if (!(target instanceof Element) || !target.closest("[data-current-conversion-form]")) return;

  const note = document.querySelector<HTMLElement>("[data-previous-result-note]");
  if (note) {
    note.hidden = false;
    note.textContent = "Updating — this result still belongs to the previous inputs.";
  }
});

document.addEventListener("htmx:beforeSwap", (event) => {
  const detail = (
    event as CustomEvent<{
      xhr: XMLHttpRequest;
      shouldSwap: boolean;
      isError: boolean;
      target?: Element;
    }>
  ).detail;

  if (![422, 502, 503].includes(detail.xhr.status)) return;

  // Validation/degraded fragments are intentionally renderable. Only converter
  // failures should mark the previous conversion as preserved; other progressive
  // surfaces (for example payment estimates) have their own error UI.
  detail.shouldSwap = true;
  detail.isError = false;
  if (detail.target?.id !== "converter-panel") return;

  const note = document
    .getElementById("conversion-result-region")
    ?.querySelector<HTMLElement>("[data-previous-result-note]");
  if (note) {
    note.hidden = false;
    note.textContent =
      detail.xhr.status === 422
        ? "Previous result — fix the changed inputs to update it."
        : "Previous result — the new rate could not be loaded.";
  }
});

document.addEventListener("DOMContentLoaded", enhanceCurrentConverterBehavior);
document.addEventListener("htmx:afterSwap", (event) => {
  enhanceCurrentConverterBehavior();
  const detail = (event as CustomEvent<{ xhr?: XMLHttpRequest }>).detail;
  const status = detail.xhr?.status;
  announceConversionResult(event.target, status);

  const target = event.target;
  const errorSummary =
    target instanceof Element && target.id === "converter-panel"
      ? target.querySelector<HTMLElement>("#conversion-error-summary")
      : null;
  if (status === 422 && focusValidationSummaryAfterSwap && errorSummary) {
    errorSummary.focus();
    focusValidationSummaryAfterSwap = false;
    restoreFocusId = null;
    return;
  }

  focusValidationSummaryAfterSwap = false;
  if (!restoreFocusId) return;
  document.getElementById(restoreFocusId)?.focus();
  restoreFocusId = null;
});

document.addEventListener("htmx:responseError", () => {
  focusValidationSummaryAfterSwap = false;
  restoreFocusId = null;
});

document.addEventListener("htmx:sendError", () => {
  focusValidationSummaryAfterSwap = false;
  restoreFocusId = null;
});
