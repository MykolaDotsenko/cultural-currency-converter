import {
  clearLocalScenarios,
  LOCAL_SCENARIOS_KEY,
  localScenarioStorageAvailable,
  readLocalScenarios,
  removeImportedLocalScenarios,
  removeLocalScenario,
  saveLocalScenario,
  type LocalScenarioRecord,
  type LocalScenarioSummary,
} from "./local-scenarios-store";

interface LocalScenarioCreateResponse {
  token: string;
  scenario: LocalScenarioSummary;
  detailUrl: string;
}

interface LocalScenarioImportResponse {
  importedCount: number;
  createdCount: number;
  items: Array<{
    localId: string;
    scenarioId: number;
    detailUrl: string;
    created: boolean;
  }>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function apiErrorMessage(payload: unknown, fallback: string): string {
  if (!isRecord(payload) || !isRecord(payload.error)) return fallback;
  const message = payload.error.message;
  return typeof message === "string" && message.trim() ? message : fallback;
}

function localScenarioOpenForm(
  action: string,
  token: string,
  label: string,
  *,
  primary = false,
): HTMLFormElement {
  const csrfToken = document.body.dataset.accountCsrfToken;
  const form = document.createElement("form");
  form.method = "post";
  form.action = action;
  form.className = "qa-inline-form";
  form.dataset.localScenarioOpenForm = "true";

  if (csrfToken) {
    const csrf = document.createElement("input");
    csrf.type = "hidden";
    csrf.name = "csrfmiddlewaretoken";
    csrf.value = csrfToken;
    form.append(csrf);
  }

  const snapshot = document.createElement("input");
  snapshot.type = "hidden";
  snapshot.name = "snapshot";
  snapshot.value = token;

  const button = document.createElement("button");
  button.type = "submit";
  button.className = primary ? "qa-primary-button" : "qa-secondary-button";
  button.textContent = label;
  form.append(snapshot, button);
  return form;
}

function saveStatus(form: HTMLFormElement, message: string): void {
  const status = form.querySelector<HTMLElement>("[data-local-scenario-save-status]");
  if (status) status.textContent = message;
}

function parseCreateResponse(value: unknown): LocalScenarioCreateResponse | null {
  if (!isRecord(value) || typeof value.token !== "string" || value.token.length > 16_384) {
    return null;
  }
  if (!isRecord(value.scenario) || typeof value.detailUrl !== "string") return null;
  const scenario = value.scenario as unknown as LocalScenarioSummary;
  return { token: value.token, scenario, detailUrl: value.detailUrl };
}

async function saveScenarioForm(form: HTMLFormElement): Promise<void> {
  const button = form.querySelector<HTMLButtonElement>("[data-local-scenario-save-button]");
  if (!button) return;

  if (!localScenarioStorageAvailable()) {
    saveStatus(
      form,
      "Browser saving is unavailable because local storage is blocked. The calculation is unchanged.",
    );
    return;
  }

  button.disabled = true;
  saveStatus(form, "Creating a signed browser-only snapshot…");
  try {
    const response = await fetch(form.action, {
      method: "POST",
      credentials: "same-origin",
      body: new FormData(form),
      headers: { Accept: "application/json" },
    });
    const payload = (await response.json()) as unknown;
    if (!response.ok) {
      throw new Error(
        apiErrorMessage(payload, "This scenario could not be saved in this browser."),
      );
    }

    const parsed = parseCreateResponse(payload);
    if (!parsed) throw new Error("The saved-scenario response was invalid.");
    const saved = saveLocalScenario(parsed.scenario, parsed.token);
    if (!saved) {
      throw new Error("Browser storage became unavailable before the scenario could be saved.");
    }

    form.dataset.localScenarioSaved = "true";
    saveStatus(
      form,
      "Saved in this browser. Sign-in will not upload it automatically; import stays explicit.",
    );
    const existing = form.querySelector<HTMLFormElement>("[data-local-scenario-open-form]");
    if (existing) existing.remove();
    const openForm = localScenarioOpenForm(
      parsed.detailUrl,
      parsed.token,
      "Open saved snapshot",
    );
    form.insertAdjacentElement("afterend", openForm);
  } catch (error) {
    saveStatus(
      form,
      error instanceof Error
        ? error.message
        : "This scenario could not be saved in this browser.",
    );
    button.disabled = false;
  }
}

function wireSaveForms(): void {
  for (const form of document.querySelectorAll<HTMLFormElement>(
    "[data-local-scenario-save-form]",
  )) {
    const button = form.querySelector<HTMLButtonElement>("[data-local-scenario-save-button]");
    if (!button) continue;

    const available = localScenarioStorageAvailable();
    if (form.dataset.localScenarioSaved !== "true") button.disabled = !available;
    saveStatus(
      form,
      available
        ? "Browser storage is available. Nothing is saved until you choose Save in this browser."
        : "Browser saving is unavailable because local storage is blocked.",
    );

    if (form.dataset.localScenarioWired === "true") continue;
    form.dataset.localScenarioWired = "true";
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      if (form.dataset.localScenarioSaved === "true") return;
      void saveScenarioForm(form);
    });
  }
}

function dateLabel(value: string): string {
  const parsed = new Date(`${value}T00:00:00Z`);
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(parsed);
}

function renderScenarioRow(
  item: LocalScenarioRecord,
  *,
  detailBaseUrl: string,
  rerender: () => void,
): HTMLElement {
  const article = document.createElement("article");
  article.className = "qa-saved-row";
  article.dataset.localScenarioId = item.id;

  const copy = document.createElement("div");
  copy.className = "qa-saved-row__copy";
  const kicker = document.createElement("p");
  kicker.className = "qa-foundation-kicker";
  kicker.textContent =
    item.kind === "shopping"
      ? "Shopping · browser-only signed snapshot"
      : "Budget · browser-only signed snapshot";
  const title = document.createElement("h3");
  title.textContent = item.title;
  const scope = document.createElement("p");
  scope.textContent = `${item.sourceAmount} ${item.sourceCurrency} → ${item.destinationCurrency} · ${item.scopeLabel}`;
  const meta = document.createElement("p");
  meta.className = "qa-saved-row__meta";
  const planning =
    item.kind === "budget" && item.durationDays !== null
      ? `${item.durationDays} day${item.durationDays === 1 ? "" : "s"} · ${item.travelers} traveler${item.travelers === 1 ? "" : "s"} · `
      : "";
  meta.textContent = `${planning}stored reference effective ${dateLabel(item.effectiveDate)}${item.stale ? " · stale fallback" : ""}`;
  copy.append(kicker, title, scope, meta);

  const actions = document.createElement("div");
  actions.className = "qa-saved-row__actions";
  const open = localScenarioOpenForm(
    detailBaseUrl,
    item.token,
    "Open stored snapshot",
    { primary: true },
  );
  const openButton = open.querySelector<HTMLButtonElement>("button");
  openButton?.setAttribute("aria-label", `Open browser-saved scenario: ${item.title}`);

  const remove = document.createElement("button");
  remove.className = "qa-secondary-button qa-destructive-button";
  remove.type = "button";
  remove.textContent = "Remove";
  remove.setAttribute("aria-label", `Remove browser-saved scenario: ${item.title}`);
  remove.addEventListener("click", () => {
    if (removeLocalScenario(item.id)) rerender();
  });
  actions.append(open, remove);
  article.append(copy, actions);
  return article;
}

function pageStatus(section: HTMLElement, message: string, tone = "neutral"): void {
  const status = section.querySelector<HTMLElement>("[data-local-scenario-page-status]");
  if (!status) return;
  status.dataset.storageTone = tone;
  status.textContent = message;
}

async function importScenarios(section: HTMLElement): Promise<void> {
  const read = readLocalScenarios();
  const button = section.querySelector<HTMLButtonElement>("[data-import-local-scenarios]");
  const importUrl = section.dataset.importUrl;
  const csrfToken = document.body.dataset.accountCsrfToken;
  if (
    read.status === "unavailable" ||
    read.state.scenarios.length === 0 ||
    !button ||
    !importUrl ||
    !csrfToken
  ) {
    return;
  }

  button.disabled = true;
  pageStatus(section, "Importing signed browser scenarios to your account…");
  try {
    const response = await fetch(importUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
        Accept: "application/json",
      },
      body: JSON.stringify({
        tokens: read.state.scenarios.map((item) => item.token),
      }),
    });
    const payload = (await response.json()) as unknown;
    if (!response.ok) {
      throw new Error(apiErrorMessage(payload, "Browser scenarios could not be imported."));
    }
    if (!isRecord(payload) || !Array.isArray(payload.items)) {
      throw new Error("The import response was invalid.");
    }
    const parsed = payload as unknown as LocalScenarioImportResponse;
    const importedIds = new Set(
      parsed.items
        .map((item) => item.localId)
        .filter((value): value is string => typeof value === "string"),
    );
    if (importedIds.size !== read.state.scenarios.length) {
      throw new Error("The server did not confirm every browser scenario.");
    }

    if (!removeImportedLocalScenarios(importedIds)) {
      pageStatus(
        section,
        "Scenarios are saved to your account, but browser copies could not be cleared. Retrying import is safe and idempotent.",
        "warning",
      );
      button.disabled = false;
      return;
    }
    window.location.reload();
  } catch (error) {
    pageStatus(
      section,
      error instanceof Error ? error.message : "Browser scenarios could not be imported.",
      "warning",
    );
    button.disabled = false;
  }
}

function renderSavedSection(): void {
  const section = document.querySelector<HTMLElement>("[data-local-scenario-section]");
  if (!section) return;

  const list = section.querySelector<HTMLElement>("[data-local-scenario-list]");
  const empty = section.querySelector<HTMLElement>("[data-local-scenario-empty]");
  const clear = section.querySelector<HTMLButtonElement>("[data-clear-local-scenarios]");
  const importButton = section.querySelector<HTMLButtonElement>("[data-import-local-scenarios]");
  const detailBaseUrl = section.dataset.detailUrl ?? "";
  if (!list || !empty || !detailBaseUrl) return;

  const read = readLocalScenarios();
  list.replaceChildren();

  if (read.status === "unavailable") {
    empty.hidden = false;
    empty.textContent = "Browser-saved scenarios are unavailable because local storage is blocked.";
    if (clear) clear.hidden = true;
    if (importButton) importButton.hidden = true;
    pageStatus(section, "Browser storage is unavailable on this device.", "warning");
    return;
  }

  for (const item of read.state.scenarios) {
    list.append(
      renderScenarioRow(item, {
        detailBaseUrl,
        rerender: renderSavedSection,
      }),
    );
  }

  const hasScenarios = read.state.scenarios.length > 0;
  empty.hidden = hasScenarios;
  if (!hasScenarios) {
    empty.textContent = "No browser-saved scenarios on this device.";
  }

  if (clear) {
    clear.hidden = !hasScenarios;
    clear.disabled = false;
    if (clear.dataset.localScenarioClearWired !== "true") {
      clear.dataset.localScenarioClearWired = "true";
      clear.addEventListener("click", () => {
        if (clearLocalScenarios()) renderSavedSection();
      });
    }
  }

  const accountMode = section.dataset.accountMode === "true";
  if (importButton) {
    importButton.hidden = !accountMode || !hasScenarios;
    importButton.disabled = false;
    if (importButton.dataset.localScenarioImportWired !== "true") {
      importButton.dataset.localScenarioImportWired = "true";
      importButton.addEventListener("click", () => void importScenarios(section));
    }
  }

  pageStatus(
    section,
    hasScenarios
      ? `${read.state.scenarios.length} signed browser-saved scenario${read.state.scenarios.length === 1 ? "" : "s"} on this device. Sign-in never imports them automatically.`
      : "Nothing is stored in the browser scenario store.",
  );
}

export function enhanceLocalScenarios(): void {
  wireSaveForms();
  renderSavedSection();
}

document.addEventListener("DOMContentLoaded", enhanceLocalScenarios);
document.addEventListener("htmx:afterSwap", enhanceLocalScenarios);
window.addEventListener("storage", (event) => {
  if (event.key === LOCAL_SCENARIOS_KEY) renderSavedSection();
});
