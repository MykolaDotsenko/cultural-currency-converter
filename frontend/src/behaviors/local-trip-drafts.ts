import {
  clearTripDrafts,
  type DraftStorage,
  normalizeTripDraft,
  readTripDrafts,
  saveTripDrafts,
  TRIP_DRAFT_KEY,
  TRIP_HANDOFF_KEY,
  type TripDraft,
  upsertTripDraft,
} from "./trip-draft-store";

function browserStorage(kind: "local" | "session"): DraftStorage | null {
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return null;
  }
}

function feedback(page: HTMLElement, message: string, warning = false): void {
  const status = page.querySelector<HTMLElement>("[data-trip-draft-status]");
  if (!status) return;
  status.textContent = message;
  status.dataset.storageTone = warning ? "warning" : "feedback";
}

function inputValue(form: HTMLFormElement, name: string): string {
  return String(new FormData(form).get(name) ?? "").trim();
}

function draftFromForm(form: HTMLFormElement, existing?: TripDraft): TripDraft | null {
  const candidate = {
    id: existing?.id ?? crypto.randomUUID(),
    title: inputValue(form, "title"),
    destination: inputValue(form, "destination")
      .split(":")
      .map((part, index) => (index === 0 ? part.toUpperCase() : part.toLowerCase()))
      .join(":"),
    sourceCurrency: inputValue(form, "sourceCurrency").toUpperCase(),
    amount: inputValue(form, "amount"),
    travelers: Number(inputValue(form, "travelers")),
    durationDays: Number(inputValue(form, "durationDays")),
    startDate: inputValue(form, "startDate"),
    updatedAt: new Date().toISOString(),
  };
  return normalizeTripDraft(candidate);
}

function fillForm(form: HTMLFormElement, draft: TripDraft): void {
  const fields: Record<string, string> = {
    title: draft.title,
    destination: draft.destination,
    sourceCurrency: draft.sourceCurrency,
    amount: draft.amount,
    travelers: String(draft.travelers),
    durationDays: String(draft.durationDays),
    startDate: draft.startDate,
  };
  for (const [name, value] of Object.entries(fields)) {
    const control = form.elements.namedItem(name);
    if (control instanceof HTMLInputElement) control.value = value;
  }
}

function renderDrafts(page: HTMLElement): void {
  if (page.dataset.accountMode === "true") return;
  const storage = browserStorage("local");
  const result = readTripDrafts(storage);
  const list = page.querySelector<HTMLElement>("[data-trip-drafts-list]");
  const empty = page.querySelector<HTMLElement>("[data-trip-drafts-empty]");
  const clear = page.querySelector<HTMLButtonElement>("[data-trip-drafts-clear]");
  const save = page.querySelector<HTMLButtonElement>("[data-trip-draft-save]");
  if (!list || !empty || !clear || !save) return;
  list.replaceChildren();

  if (result.status !== "ok") {
    empty.hidden = false;
    empty.textContent =
      result.status === "invalid"
        ? "The stored draft data is invalid. Nothing was overwritten. Clear these local drafts only if you are ready to discard them."
        : "Browser storage is unavailable. You can still plan a destination without saving a draft.";
    clear.hidden = result.status !== "invalid";
    save.disabled = true;
    feedback(page, empty.textContent, true);
    return;
  }

  save.disabled = false;
  clear.hidden = result.drafts.length === 0;
  empty.hidden = result.drafts.length > 0;
  empty.textContent = "No local trip drafts yet. Save only the inputs you want to revisit.";
  const plannerUrl = page.dataset.destinationModeUrl;
  if (!plannerUrl) return;

  for (const draft of result.drafts) {
    const row = document.createElement("article");
    row.className = "qa-saved-row";
    const description = document.createElement("div");
    description.className = "qa-saved-row__copy";
    const title = document.createElement("h3");
    title.textContent = draft.title;
    const main = document.createElement("p");
    main.textContent = `${draft.amount} ${draft.sourceCurrency} · ${draft.destination} · ${draft.travelers} traveller(s) · ${draft.durationDays} day(s)`;
    const meta = document.createElement("p");
    meta.className = "qa-saved-row__meta";
    meta.textContent = draft.startDate
      ? `Start ${draft.startDate} · Browser-only draft`
      : "Browser-only draft · No FX rate saved";
    description.append(title, main, meta);

    const actions = document.createElement("div");
    actions.className = "qa-saved-row__actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "qa-secondary-button";
    edit.textContent = "Edit";
    edit.setAttribute("aria-label", `Edit local trip draft: ${draft.title}`);
    edit.addEventListener("click", () => {
      const form = page.querySelector<HTMLFormElement>("[data-trip-draft-form]");
      if (!form) return;
      fillForm(form, draft);
      form.dataset.editId = draft.id;
      save.textContent = "Update local draft";
      form.querySelector<HTMLInputElement>('input[name="title"]')?.focus();
      feedback(
        page,
        "Editing this browser-only draft. Changes are not saved until you select Update.",
      );
    });

    const plan = document.createElement("button");
    plan.type = "button";
    plan.className = "qa-primary-button";
    plan.textContent = "Continue planning";
    plan.setAttribute("aria-label", `Continue planning local trip draft: ${draft.title}`);
    plan.addEventListener("click", () => {
      const session = browserStorage("session");
      try {
        if (!session) throw new Error("Session storage unavailable");
        session.setItem(
          TRIP_HANDOFF_KEY,
          JSON.stringify({
            destination: draft.destination,
            sourceCurrency: draft.sourceCurrency,
            amount: draft.amount,
          }),
        );
        window.location.assign(`${plannerUrl}#local-trip-draft`);
      } catch {
        feedback(
          page,
          "Could not prepare the draft. Browser storage is unavailable; no inputs were sent.",
          true,
        );
      }
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "qa-secondary-button qa-destructive-button";
    remove.textContent = "Remove";
    remove.setAttribute("aria-label", `Remove local trip draft: ${draft.title}`);
    remove.addEventListener("click", () => {
      if (!window.confirm(`Remove the local draft "${draft.title}" from this browser?`)) return;
      const latest = readTripDrafts(storage);
      if (
        latest.status !== "ok" ||
        !saveTripDrafts(
          storage,
          latest.drafts.filter((item) => item.id !== draft.id),
        )
      ) {
        feedback(page, "The local draft could not be removed; it is unchanged.", true);
        return;
      }
      const form = page.querySelector<HTMLFormElement>("[data-trip-draft-form]");
      if (form?.dataset.editId === draft.id) {
        form.reset();
        delete form.dataset.editId;
        save.textContent = "Save local draft";
      }
      renderDrafts(page);
      feedback(page, "Local draft removed from this browser.");
    });
    actions.append(edit, plan, remove);
    row.append(description, actions);
    list.append(row);
  }
}

function wireDraftEditor(page: HTMLElement): void {
  if (page.dataset.accountMode === "true" || page.dataset.tripDraftWired === "true") return;
  page.dataset.tripDraftWired = "true";
  const form = page.querySelector<HTMLFormElement>("[data-trip-draft-form]");
  const clear = page.querySelector<HTMLButtonElement>("[data-trip-drafts-clear]");
  const save = page.querySelector<HTMLButtonElement>("[data-trip-draft-save]");
  if (!form || !clear || !save) return;

  // The server-rendered form is inert until this handler is installed.
  // This avoids a no-JavaScript GET leak *and* removes layout shift on hydration.
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const storage = browserStorage("local");
    const latest = readTripDrafts(storage);
    if (latest.status !== "ok") {
      feedback(page, "Could not save; existing browser data was not overwritten.", true);
      return;
    }
    const editing = form.dataset.editId;
    const previous = editing ? latest.drafts.find((item) => item.id === editing) : undefined;
    if (editing && !previous) {
      feedback(page, "This draft changed in another tab. Reload the list before editing.", true);
      return;
    }
    const draft = draftFromForm(form, previous);
    if (!draft) {
      feedback(
        page,
        "Check the title, ISO currency, destination, amount, travellers, days and date.",
        true,
      );
      return;
    }
    const next = upsertTripDraft(latest.drafts, draft);
    if (!next || !saveTripDrafts(storage, next)) {
      feedback(
        page,
        "Unable to save. The maximum is eight drafts, or browser storage may be full.",
        true,
      );
      return;
    }
    form.reset();
    delete form.dataset.editId;
    save.textContent = "Save local draft";
    renderDrafts(page);
    feedback(page, "Saved on this device only. Nothing was sent to the server.");
  });

  page
    .querySelector<HTMLButtonElement>("[data-trip-draft-reset]")
    ?.addEventListener("click", () => {
      form.reset();
      delete form.dataset.editId;
      save.textContent = "Save local draft";
      feedback(page, "Unsaved edits discarded. Stored drafts remain unchanged.");
    });

  clear.addEventListener("click", () => {
    if (!window.confirm("Permanently clear all trip drafts stored in this browser?")) return;
    if (!clearTripDrafts(browserStorage("local"))) {
      feedback(page, "Browser drafts could not be cleared.", true);
      return;
    }
    form.reset();
    delete form.dataset.editId;
    save.textContent = "Save local draft";
    renderDrafts(page);
    feedback(page, "All local trip drafts removed from this browser.");
  });

  form.querySelectorAll<HTMLInputElement | HTMLButtonElement>("input, button").forEach((control) => {
    control.disabled = false;
  });
  renderDrafts(page);
}

function handoffToDestinationForm(): void {
  if (window.location.hash !== "#local-trip-draft") return;
  const form = document.querySelector<HTMLFormElement>("[data-trip-draft-prefill]");
  if (!form || form.dataset.draftPrefillAttempted === "true") return;
  form.dataset.draftPrefillAttempted = "true";
  const status = document.querySelector<HTMLElement>("[data-trip-draft-prefill-status]");
  const storage = browserStorage("session");
  let value: unknown = null;
  try {
    if (storage) {
      const raw = storage.getItem(TRIP_HANDOFF_KEY);
      if (raw && raw.length < 1024) value = JSON.parse(raw);
      storage.removeItem(TRIP_HANDOFF_KEY);
    }
  } catch {
    value = null;
  }
  window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
  const amount = form.querySelector<HTMLInputElement>('input[name="amount"]');
  const currency = form.querySelector<HTMLSelectElement>('select[name="source_currency"]');
  const destination = form.querySelector<HTMLSelectElement>('select[name="destination"]');
  const data = value as Record<string, unknown> | null;
  if (
    !data ||
    typeof data !== "object" ||
    !amount ||
    !currency ||
    !destination ||
    typeof data.amount !== "string" ||
    !/^\d{1,12}(?:\.\d{1,4})?$/.test(data.amount) ||
    !/[1-9]/.test(data.amount) ||
    typeof data.sourceCurrency !== "string" ||
    typeof data.destination !== "string" ||
    !Array.from(currency.options).some((opt) => opt.value === data.sourceCurrency) ||
    !Array.from(destination.options).some((opt) => opt.value === data.destination)
  ) {
    if (status) {
      status.hidden = false;
      status.textContent =
        "Draft inputs could not be prefilled. Select a currently supported currency and destination manually; the local draft is unchanged.";
    }
    return;
  }
  amount.value = data.amount;
  currency.value = data.sourceCurrency;
  destination.value = data.destination;
  if (status) {
    status.hidden = false;
    status.textContent =
      "Draft amount, currency and destination restored on this page only. Confirm the details before submitting; travellers and dates remain in your browser draft. No rate was requested.";
  }
}

let watchingStorage = false;

export function enhanceLocalTripDrafts(): void {
  const page = document.querySelector<HTMLElement>("[data-local-saved-state-page]");
  if (page?.dataset.accountMode === "false") wireDraftEditor(page);
  handoffToDestinationForm();
  if (!watchingStorage) {
    watchingStorage = true;
    window.addEventListener("storage", (event) => {
      if (event.key !== TRIP_DRAFT_KEY) return;
      const current = document.querySelector<HTMLElement>("[data-local-saved-state-page]");
      if (current?.dataset.accountMode === "false") renderDrafts(current);
    });
  }
}
