import Combobox from "@github/combobox-nav";

import { requestFocusRestore } from "./current-converter";

const activeComboboxes = new WeakMap<HTMLInputElement, Combobox>();

function currentConversionForm(): HTMLFormElement | null {
  return document.querySelector<HTMLFormElement>("[data-current-conversion-form]");
}

function refreshAfterSelection(form: HTMLFormElement, focusId: string): void {
  if (form.dataset.hasResult === "true") {
    requestFocusRestore(focusId);
    form.requestSubmit();
  }
}

function commitOption(dialog: HTMLDialogElement, option: HTMLElement): void {
  const side = dialog.dataset.pickerDialog;
  const form = currentConversionForm();
  if (!side || !form) return;

  const countrySelect = form.querySelector<HTMLSelectElement>(`[name="${side}_country"]`);
  const currencySelect = form.querySelector<HTMLSelectElement>(`[name="${side}_currency"]`);
  const trigger = document.querySelector<HTMLButtonElement>(`[data-picker-trigger="${side}"]`);
  if (!countrySelect || !currencySelect || !trigger) return;

  const countryCode = option.dataset.countryCode ?? "";
  const currencyCode = option.dataset.currencyCode ?? "";
  if (!currencyCode) return;

  if (side === "destination" && countrySelect.value !== countryCode) {
    const city = form.querySelector<HTMLInputElement>('input[name="destination_city_slug"]');
    if (city) city.value = "";
  }

  countrySelect.value = countryCode;
  currencySelect.value = currencyCode;

  const country = trigger.querySelector<HTMLElement>(".qa-selector-trigger__country");
  const currency = trigger.querySelector<HTMLElement>(".qa-selector-trigger__currency");

  const countryName = option.dataset.countryName || "No country context";
  const currencyName = option.dataset.currencyName || currencyCode;

  if (country) country.textContent = countryName;
  if (currency) currency.textContent = `${currencyName} · ${currencyCode}`;

  const roleLabel = side === "source" ? "source" : "destination";
  trigger.setAttribute(
    "aria-label",
    `Change ${roleLabel} country or currency. Current ${roleLabel}: ${countryName}, ${currencyName} ${currencyCode}.`,
  );

  const input = dialog.querySelector<HTMLInputElement>('input[type="search"]');
  if (input) input.value = "";

  dialog.close();
  refreshAfterSelection(form, trigger.id);
}

function wireCombobox(dialog: HTMLDialogElement): void {
  if (!dialog.open) return;

  const input = dialog.querySelector<HTMLInputElement>('input[role="combobox"]');
  const list = dialog.querySelector<HTMLElement>('[role="listbox"]');
  if (!input || !list) return;

  activeComboboxes.get(input)?.destroy();

  const combobox = new Combobox(input, list, {
    tabInsertsSuggestions: false,
    firstOptionSelectionMode: "none",
    scrollIntoViewOptions: { block: "nearest" },
  });
  combobox.start();
  activeComboboxes.set(input, combobox);

  if (list.dataset.commitWired !== "true") {
    list.dataset.commitWired = "true";
    list.addEventListener("combobox-commit", (event) => {
      const target = event.target;
      const option =
        target instanceof Element ? target.closest<HTMLElement>("[data-picker-option]") : null;
      if (option) commitOption(dialog, option);
    });
  }
}

function enhanceDialog(dialog: HTMLDialogElement): void {
  const side = dialog.dataset.pickerDialog;
  if (!side) return;

  if (dialog.dataset.enhanced !== "true") {
    dialog.dataset.enhanced = "true";
    const trigger = document.querySelector<HTMLButtonElement>(`[data-picker-trigger="${side}"]`);
    const fallback = document.querySelector<HTMLElement>(`[data-native-selection="${side}"]`);
    const close = dialog.querySelector<HTMLButtonElement>(`[data-picker-close="${side}"]`);
    const input = dialog.querySelector<HTMLInputElement>('input[type="search"]');

    const hasFallbackErrors = fallback?.dataset.hasErrors === "true";
    if (trigger && !hasFallbackErrors) {
      trigger.hidden = false;
      trigger.setAttribute("aria-expanded", "false");
      trigger.addEventListener("click", () => {
        if (!dialog.open) dialog.showModal();
        trigger.setAttribute("aria-expanded", "true");
        input?.focus();
      });

      dialog.addEventListener("close", () => {
        const comboboxInput = dialog.querySelector<HTMLInputElement>('input[role="combobox"]');
        if (comboboxInput) activeComboboxes.get(comboboxInput)?.stop();
        trigger.setAttribute("aria-expanded", "false");
        trigger.focus();
      });
    }

    if (fallback && !hasFallbackErrors) fallback.hidden = true;
    close?.addEventListener("click", () => dialog.close());
  }

  wireCombobox(dialog);
}

export function enhanceCurrentConverter(): void {
  for (const dialog of document.querySelectorAll<HTMLDialogElement>("[data-picker-dialog]")) {
    enhanceDialog(dialog);
  }
}

document.addEventListener("DOMContentLoaded", enhanceCurrentConverter);
document.addEventListener("htmx:afterSwap", enhanceCurrentConverter);
