import {
  normalizeBrowserScenario,
  readState,
  upsertBrowserScenario,
  writeState,
} from "./local-saved-state-store";

interface BrowserScenarioIssueResponse {
  scenario?: unknown;
  error?: {
    code?: string;
    message?: string;
  };
}

function setStatus(form: HTMLFormElement, message: string): void {
  const status = form.querySelector<HTMLElement>("[data-browser-scenario-save-status]");
  if (status) {
    status.textContent = message;
    status.setAttribute("aria-live", "polite");
  }
}

async function saveBrowserScenario(form: HTMLFormElement): Promise<void> {
  const button = form.querySelector<HTMLButtonElement>("[data-browser-scenario-save]");
  if (!button) return;

  const read = readState();
  if (read.status === "unavailable") {
    setStatus(
      form,
      "Browser-only saving is unavailable because local storage is blocked. Your result is unchanged.",
    );
    return;
  }

  button.disabled = true;
  setStatus(form, "Preparing a private browser-only snapshot…");
  try {
    const response = await fetch(form.action, {
      method: "POST",
      credentials: "same-origin",
      body: new FormData(form),
      headers: {
        Accept: "application/json",
      },
    });
    const payload = (await response.json()) as BrowserScenarioIssueResponse;
    if (!response.ok) {
      throw new Error(
        payload.error?.message || "Browser save failed with status " + String(response.status) + ".",
      );
    }

    const scenario = normalizeBrowserScenario(payload.scenario);
    if (!scenario) {
      throw new Error("Browser save returned an invalid scenario snapshot.");
    }

    const latest = readState();
    if (latest.status === "unavailable") {
      throw new Error("Browser storage became unavailable before the snapshot could be saved.");
    }
    if (!writeState(upsertBrowserScenario(latest.state, scenario))) {
      throw new Error("Browser storage could not be updated.");
    }

    form.dataset.browserScenarioSaved = scenario.id;
    button.disabled = true;
    button.textContent = "Saved in this browser";
    setStatus(
      form,
      "Saved only in this browser. Sign-in will not upload it automatically; import is always explicit.",
    );
  } catch (error) {
    button.disabled = false;
    setStatus(
      form,
      error instanceof Error
        ? error.message
        : "This scenario could not be saved in the browser. Your result is unchanged.",
    );
  }
}

export function wireBrowserScenarioForms(): void {
  for (const form of document.querySelectorAll<HTMLFormElement>("[data-browser-scenario-form]")) {
    if (form.dataset.browserScenarioWired === "true") continue;
    form.dataset.browserScenarioWired = "true";
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      void saveBrowserScenario(form);
    });
  }
}
