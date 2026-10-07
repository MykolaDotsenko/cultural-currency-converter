import { accountCurrencySyncAvailable, importLocalCurrenciesToAccount } from "./account-currencies";
import { accountPlaceSyncAvailable, importLocalPlacesToAccount } from "./account-places";
import {
  type LocalPreferencesV1,
  type PairContext,
  type RateMode,
  type ReadResult,
  type RecentConversion,
  readState,
  normalizeSavedCurrency,
  type SavedCurrency,
  type SavedPlace,
  toggleCurrencyInState,
  writeState,
} from "./local-saved-state-store";

const WRITE_FAILURE_MESSAGE =
  "Browser storage could not be updated. Your converter still works and no data was sent to the server.";

function countryLabel(code: string, name: string): string {
  return name || code || "No country context";
}

function countrySummary(pair: PairContext): string {
  return `${countryLabel(pair.sourceCountry, pair.sourceCountryName)} → ${countryLabel(
    pair.destinationCountry,
    pair.destinationCountryName,
  )}`;
}

function dateLabel(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(`${value}T00:00:00Z`));
}

function savedAtLabel(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(new Date(value));
}

function dayGroupLabel(value: string): string {
  const date = new Date(value);
  const localDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dayDifference = Math.round((today.getTime() - localDay.getTime()) / 86_400_000);
  if (dayDifference === 0) return "Today";
  if (dayDifference === 1) return "Yesterday";
  return new Intl.DateTimeFormat(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
  }).format(date);
}

function linkForPair(
  converterUrl: string,
  pair: PairContext,
  options: { amount?: string; rateMode?: RateMode; requestedDate?: string; swap?: boolean } = {},
): string {
  const url = new URL(converterUrl, window.location.origin);
  const sourceCurrency = options.swap ? pair.destinationCurrency : pair.sourceCurrency;
  const destinationCurrency = options.swap ? pair.sourceCurrency : pair.destinationCurrency;
  const sourceCountry = options.swap ? pair.destinationCountry : pair.sourceCountry;
  const destinationCountry = options.swap ? pair.sourceCountry : pair.destinationCountry;

  if (options.amount) {
    url.searchParams.set("convert", "1");
    url.searchParams.set("amount", options.amount);
  } else {
    url.searchParams.set("load", "1");
  }
  url.searchParams.set("source_currency", sourceCurrency);
  url.searchParams.set("destination_currency", destinationCurrency);
  if (sourceCountry) url.searchParams.set("source_country", sourceCountry);
  if (destinationCountry) url.searchParams.set("destination_country", destinationCountry);
  if (options.rateMode === "historical" && options.requestedDate) {
    url.searchParams.set("rate_mode", "historical");
    url.searchParams.set("requested_date", options.requestedDate);
  }
  return `${url.pathname}${url.search}`;
}

type SavedActionTone = "primary" | "secondary" | "tertiary";

function actionLink(
  text: string,
  href: string,
  accessibleName = text,
  tone: SavedActionTone = "secondary",
): HTMLAnchorElement {
  const element = document.createElement("a");
  element.className =
    tone === "primary"
      ? "qa-primary-button"
      : tone === "tertiary"
        ? "qa-saved-row__text-action"
        : "qa-secondary-button";
  element.textContent = text;
  element.href = href;
  if (accessibleName !== text) element.setAttribute("aria-label", accessibleName);
  return element;
}

function actionButton(text: string, action: () => void, accessibleName = text): HTMLButtonElement {
  const element = document.createElement("button");
  element.className = "qa-secondary-button";
  element.type = "button";
  element.textContent = text;
  if (accessibleName !== text) element.setAttribute("aria-label", accessibleName);
  element.addEventListener("click", action);
  return element;
}

function setEmptyState(
  element: HTMLElement,
  message: string,
  actionText: string,
  href: string,
): void {
  const copy = document.createElement("span");
  copy.textContent = message;
  const action = document.createElement("a");
  action.className = "qa-saved-row__text-action qa-saved-empty__action";
  action.href = href;
  action.textContent = actionText;
  element.replaceChildren(copy, action);
}

function persistAndRender(state: LocalPreferencesV1, successMessage: string): void {
  renderSavedPage(writeState(state) ? successMessage : WRITE_FAILURE_MESSAGE);
}

function currencyConverterUrl(
  converterUrl: string,
  code: string,
  side: "source" | "destination",
): string {
  const url = new URL(converterUrl, window.location.origin);
  url.searchParams.set("load", "1");
  url.searchParams.set(side === "source" ? "source_currency" : "destination_currency", code);
  return `${url.pathname}${url.search}`;
}

function renderCurrencies(
  page: HTMLElement,
  state: LocalPreferencesV1,
  converterUrl: string,
): void {
  const list = page.querySelector<HTMLElement>("[data-currencies-list]");
  const empty = page.querySelector<HTMLElement>("[data-currencies-empty]");
  if (!list || !empty) return;

  list.replaceChildren();
  empty.removeAttribute("data-local-pending");
  empty.textContent = "No browser-saved currencies yet.";
  empty.hidden = state.currencies.length > 0;

  for (const currency of state.currencies) {
    const article = document.createElement("article");
    article.className = "qa-saved-row";
    article.dataset.savedCurrencyCode = currency.code;

    const copy = document.createElement("div");
    copy.className = "qa-saved-row__copy";
    const title = document.createElement("h3");
    title.textContent = `${currency.code} · ${currency.name || "Currency"}`;
    const meta = document.createElement("p");
    meta.className = "qa-saved-row__meta";
    meta.textContent =
      `Saved ${savedAtLabel(currency.savedAt)} · currency only, no amount or country stored`;
    copy.append(title, meta);

    const actions = document.createElement("div");
    actions.className = "qa-saved-row__actions";
    actions.append(
      actionLink(
        "Use as source",
        currencyConverterUrl(converterUrl, currency.code, "source"),
        `Use ${currency.code} as source currency`,
        "primary",
      ),
      actionLink(
        "Use as destination",
        currencyConverterUrl(converterUrl, currency.code, "destination"),
        `Use ${currency.code} as destination currency`,
      ),
      actionButton(
        "Remove",
        () => {
          const read = readState();
          persistAndRender(
            {
              ...read.state,
              currencies: read.state.currencies.filter((item) => item.code !== currency.code),
            },
            `${currency.code} removed from this browser.`,
          );
        },
        `Remove saved currency: ${currency.code}`,
      ),
    );
    article.append(copy, actions);
    list.append(article);
  }
}

function renderFavourites(
  page: HTMLElement,
  state: LocalPreferencesV1,
  converterUrl: string,
): void {
  if (page.dataset.accountMode === "true") return;
  const list = page.querySelector<HTMLElement>("[data-favourites-list]");
  const empty = page.querySelector<HTMLElement>("[data-favourites-empty]");
  if (!list || !empty) return;

  list.replaceChildren();
  empty.removeAttribute("data-local-pending");
  setEmptyState(
    empty,
    "No saved pairs yet. Save a pair after a conversion for quicker access.",
    "Convert a pair",
    converterUrl,
  );
  empty.hidden = state.favourites.length > 0;

  for (const favourite of state.favourites) {
    const article = document.createElement("article");
    article.className = "qa-saved-row";
    article.dataset.savedPairId = favourite.id;

    const copy = document.createElement("div");
    copy.className = "qa-saved-row__copy";
    const title = document.createElement("h3");
    title.textContent = `${favourite.sourceCurrency} → ${favourite.destinationCurrency}`;
    const countries = document.createElement("p");
    countries.textContent = countrySummary(favourite);
    const meta = document.createElement("p");
    meta.className = "qa-saved-row__meta";
    meta.textContent = `Saved ${savedAtLabel(favourite.savedAt)} · amount is not stored`;
    copy.append(title, countries, meta);

    const actions = document.createElement("div");
    actions.className = "qa-saved-row__actions";
    const pairActionName = `${favourite.sourceCurrency} to ${favourite.destinationCurrency}`;
    actions.append(
      actionLink(
        "Use pair",
        linkForPair(converterUrl, favourite),
        `Use pair: ${pairActionName}`,
        "primary",
      ),
      ...(favourite.destinationCountry
        ? [
            actionLink(
              "Compare",
              destinationComparisonUrl(
                page.dataset.comparisonUrl ?? "/compare/",
                favourite.destinationCountry,
              ),
              `Compare destination: ${countryLabel(
                favourite.destinationCountry,
                favourite.destinationCountryName,
              )}`,
            ),
          ]
        : []),
      actionLink(
        "Reverse pair",
        linkForPair(converterUrl, favourite, { swap: true }),
        `Reverse pair: ${pairActionName}`,
        "tertiary",
      ),
      actionButton(
        "Remove",
        () => {
          const read = readState();
          const next = {
            ...read.state,
            favourites: read.state.favourites.filter((item) => item.id !== favourite.id),
          };
          persistAndRender(next, "Removed from saved.");
        },
        `Remove saved pair: ${pairActionName}`,
      ),
    );
    article.append(copy, actions);
    list.append(article);
  }
}

function placeLabel(place: SavedPlace): string {
  return place.cityName ? `${place.cityName}, ${place.countryName}` : place.countryName;
}

function placeConverterUrl(converterUrl: string, place: SavedPlace): string {
  const url = new URL(converterUrl, window.location.origin);
  url.searchParams.set("load", "1");
  url.searchParams.set("destination_country", place.countryCode);
  url.searchParams.set("destination_currency", place.currencyCode);
  if (place.citySlug) url.searchParams.set("destination_city_slug", place.citySlug);
  return `${url.pathname}${url.search}`;
}

function destinationComparisonUrl(baseUrl: string, token: string): string {
  const url = new URL(baseUrl, window.location.origin);
  url.searchParams.set("left_destination", token);
  return `${url.pathname}${url.search}`;
}

function renderPlaces(
  page: HTMLElement,
  state: LocalPreferencesV1,
  converterUrl: string,
  comparisonUrl: string,
): void {
  const list = page.querySelector<HTMLElement>("[data-places-list]");
  const empty = page.querySelector<HTMLElement>("[data-places-empty]");
  if (!list || !empty) return;

  list.replaceChildren();
  empty.removeAttribute("data-local-pending");
  setEmptyState(
    empty,
    "No saved places yet. Save a reviewed country or city from Explore.",
    "Explore destinations",
    page.dataset.exploreUrl ?? "/explore/",
  );
  empty.hidden = state.places.length > 0;

  for (const place of state.places) {
    const article = document.createElement("article");
    article.className = "qa-saved-row";
    article.dataset.savedPlaceId = place.id;

    const copy = document.createElement("div");
    copy.className = "qa-saved-row__copy";
    const kicker = document.createElement("p");
    kicker.className = "qa-foundation-kicker";
    kicker.textContent = place.citySlug
      ? "City · saved in this browser"
      : "Country · saved in this browser";
    const title = document.createElement("h3");
    title.textContent = placeLabel(place);
    const meta = document.createElement("p");
    meta.className = "qa-saved-row__meta";
    meta.textContent = `${place.currencyCode} · Saved ${savedAtLabel(place.savedAt)}`;
    copy.append(kicker, title, meta);

    const actions = document.createElement("div");
    actions.className = "qa-saved-row__actions";
    actions.append(
      actionLink(
        "Convert",
        placeConverterUrl(converterUrl, place),
        `Convert for ${placeLabel(place)}`,
        "primary",
      ),
      actionLink(
        "Compare",
        destinationComparisonUrl(comparisonUrl, place.token),
        `Compare destination: ${placeLabel(place)}`,
      ),
    );
    if (place.citySlug) {
      actions.append(
        actionLink(
          "City profile",
          `/city/${encodeURIComponent(place.countryCode)}/${encodeURIComponent(place.citySlug)}/`,
          `Open city profile: ${placeLabel(place)}`,
          "tertiary",
        ),
      );
    }
    actions.append(
      actionButton(
        "Remove",
        () => {
          const read = readState();
          const next = {
            ...read.state,
            places: read.state.places.filter((item) => item.token !== place.token),
          };
          persistAndRender(next, "Place removed from this browser.");
        },
        `Remove saved place: ${placeLabel(place)}`,
      ),
    );
    article.append(copy, actions);
    list.append(article);
  }
}

function recentMeta(recent: RecentConversion): string {
  if (recent.rateMode === "historical") {
    return `Historical · requested ${dateLabel(recent.requestedDate)} · observation ${dateLabel(
      recent.effectiveDate,
    )}`;
  }
  return `Latest available · effective ${dateLabel(recent.effectiveDate)}`;
}

function renderRecents(page: HTMLElement, state: LocalPreferencesV1, converterUrl: string): void {
  const list = page.querySelector<HTMLElement>("[data-recents-list]");
  const empty = page.querySelector<HTMLElement>("[data-recents-empty]");
  if (!list || !empty) return;

  list.replaceChildren();
  empty.removeAttribute("data-local-pending");
  setEmptyState(
    empty,
    page.dataset.accountMode === "true"
      ? "No browser-only recent conversions here."
      : "No recent conversions in this browser yet.",
    "Start a conversion",
    converterUrl,
  );
  empty.hidden = state.recent.length > 0;
  let activeDay = "";

  for (const recent of state.recent) {
    const day = dayGroupLabel(recent.convertedAt);
    if (day !== activeDay) {
      activeDay = day;
      const heading = document.createElement("h3");
      heading.className = "qa-saved-list__date";
      heading.textContent = day;
      list.append(heading);
    }

    const article = document.createElement("article");
    article.className = "qa-saved-row";
    article.dataset.recentConversionId = recent.id;

    const copy = document.createElement("div");
    copy.className = "qa-saved-row__copy";
    const title = document.createElement("h4");
    title.textContent = `${recent.amount} ${recent.sourceCurrency} → ${recent.outputAmount} ${recent.destinationCurrency}`;
    const countries = document.createElement("p");
    countries.textContent = countrySummary(recent);
    const meta = document.createElement("p");
    meta.className = "qa-saved-row__meta";
    meta.textContent = recentMeta(recent);
    copy.append(title, countries, meta);

    const actions = document.createElement("div");
    actions.className = "qa-saved-row__actions";
    const conversionActionName = `${recent.amount} ${recent.sourceCurrency} to ${recent.destinationCurrency}`;
    actions.append(
      actionLink(
        "Repeat",
        linkForPair(converterUrl, recent, {
          amount: recent.amount,
          rateMode: recent.rateMode,
          requestedDate: recent.requestedDate,
        }),
        `Repeat conversion: ${conversionActionName}`,
        "primary",
      ),
      ...(recent.destinationCountry
        ? [
            actionLink(
              "Compare",
              destinationComparisonUrl(
                page.dataset.comparisonUrl ?? "/compare/",
                recent.destinationCountry,
              ),
              `Compare destination: ${countryLabel(
                recent.destinationCountry,
                recent.destinationCountryName,
              )}`,
            ),
          ]
        : []),
      actionLink(
        "Swap",
        linkForPair(converterUrl, recent, {
          amount: recent.amount,
          rateMode: recent.rateMode,
          requestedDate: recent.requestedDate,
          swap: true,
        }),
        `Swap conversion: ${conversionActionName}`,
        "tertiary",
      ),
      actionButton(
        "Remove",
        () => {
          const read = readState();
          const next = {
            ...read.state,
            recent: read.state.recent.filter((item) => item.id !== recent.id),
          };
          persistAndRender(next, "Recent conversion removed.");
        },
        `Remove recent conversion: ${conversionActionName}`,
      ),
    );
    article.append(copy, actions);
    list.append(article);
  }
}

function setStorageStatus(page: HTMLElement, read: ReadResult, overrideMessage = ""): void {
  const status = page.querySelector<HTMLElement>("[data-local-storage-status]");
  if (!status) return;

  status.removeAttribute("data-local-pending");
  const accountMode = page.dataset.accountMode === "true";
  const accountHistoryEnabled = page.dataset.accountHistoryEnabled === "true";
  if (overrideMessage) {
    status.dataset.storageTone = "feedback";
    status.setAttribute("aria-live", "polite");
    status.textContent = overrideMessage;
  } else if (read.status === "unavailable") {
    status.dataset.storageTone = "warning";
    status.setAttribute("aria-live", "polite");
    status.textContent = accountMode
      ? "Account data remains available. Browser storage is unavailable, so browser-only history is disabled."
      : "Browser storage is unavailable. Saved pairs and recent history are disabled; conversion still works.";
  } else if (read.status === "recovered") {
    status.dataset.storageTone = "warning";
    status.setAttribute("aria-live", "polite");
    status.textContent = accountMode
      ? "Account data remains available. Some browser-only recent history was unreadable and has been ignored."
      : "Some local saved data was unreadable or outdated and has been ignored. Nothing was sent to the server.";
  } else {
    status.dataset.storageTone = "neutral";
    status.setAttribute("aria-live", "off");
    status.textContent = accountMode
      ? accountHistoryEnabled
        ? `Account history is on · Browser-only recent entries on this device: ${read.state.recent.length}.`
        : `Account history is off · Browser-only recent entries on this device: ${read.state.recent.length}.`
      : `Stored locally in this browser · ${read.state.currencies.length} currencies · ${read.state.places.length} places · ${read.state.favourites.length} pairs · ${read.state.recent.length} recent.`;
  }
}

function renderSavedPage(overrideMessage = ""): void {
  const page = document.querySelector<HTMLElement>("[data-local-saved-state-page]");
  if (!page) return;

  const read = readState();
  const converterUrl = page.dataset.converterUrl ?? "/";
  const comparisonUrl = page.dataset.comparisonUrl ?? "/compare/";
  setStorageStatus(page, read, overrideMessage);

  const clearCurrencies = page.querySelector<HTMLButtonElement>("[data-clear-currencies]");
  const importCurrencies = page.querySelector<HTMLButtonElement>("[data-import-local-currencies]");
  const importCurrencySummary = page.querySelector<HTMLElement>(
    "[data-local-currency-migration-summary]",
  );
  const clearFavourites = page.querySelector<HTMLButtonElement>("[data-clear-favourites]");
  const clearPlaces = page.querySelector<HTMLButtonElement>("[data-clear-places]");
  const clearRecents = page.querySelector<HTMLButtonElement>("[data-clear-recents]");
  const importPlaces = page.querySelector<HTMLButtonElement>("[data-import-local-places]");
  const importSummary = page.querySelector<HTMLElement>("[data-local-place-migration-summary]");
  const unavailable = read.status === "unavailable";
  if (clearCurrencies) {
    const canClearCurrencies = !unavailable && read.state.currencies.length > 0;
    clearCurrencies.hidden = !canClearCurrencies;
    clearCurrencies.disabled = !canClearCurrencies;
  }
  if (importCurrencies) {
    const canImport =
      page.dataset.accountMode === "true" &&
      accountCurrencySyncAvailable() &&
      !unavailable &&
      read.state.currencies.length > 0;
    importCurrencies.hidden = !canImport;
    importCurrencies.disabled = !canImport;
  }
  if (importCurrencySummary && page.dataset.accountMode === "true") {
    importCurrencySummary.removeAttribute("data-local-pending");
    if (unavailable) {
      importCurrencySummary.textContent =
        "Browser-only currencies cannot be read on this device.";
    } else if (read.state.currencies.length === 0) {
      importCurrencySummary.textContent =
        "No browser-only currencies are waiting to be imported.";
    } else {
      importCurrencySummary.textContent =
        `${read.state.currencies.length} browser-only currency shortcut${read.state.currencies.length === 1 ? "" : "s"} remain on this device. Import is always explicit.`;
    }
  }
  if (clearFavourites) {
    const canClearFavourites = !unavailable && read.state.favourites.length > 0;
    clearFavourites.hidden = !canClearFavourites;
    clearFavourites.disabled = !canClearFavourites;
  }
  if (clearPlaces) {
    const canClearPlaces = !unavailable && read.state.places.length > 0;
    clearPlaces.hidden = !canClearPlaces;
    clearPlaces.disabled = !canClearPlaces;
  }
  if (importPlaces) {
    const canImport =
      page.dataset.accountMode === "true" &&
      accountPlaceSyncAvailable() &&
      !unavailable &&
      read.state.places.length > 0;
    importPlaces.hidden = !canImport;
    importPlaces.disabled = !canImport;
  }
  if (importSummary && page.dataset.accountMode === "true") {
    importSummary.removeAttribute("data-local-pending");
    if (unavailable) {
      importSummary.textContent =
        "Browser-only places cannot be read on this device, so nothing can be imported.";
    } else if (read.state.places.length === 0) {
      importSummary.textContent =
        "No browser-only places are waiting to be imported on this device.";
    } else {
      importSummary.textContent = `${read.state.places.length} browser-only place${read.state.places.length === 1 ? "" : "s"} remain on this device. Import is always explicit.`;
    }
  }
  if (clearRecents) {
    const canClearRecents = !unavailable && read.state.recent.length > 0;
    clearRecents.hidden = !canClearRecents;
    clearRecents.disabled = !canClearRecents;
  }

  renderCurrencies(page, read.state, converterUrl);
  renderPlaces(page, read.state, converterUrl, comparisonUrl);
  renderFavourites(page, read.state, converterUrl);
  renderRecents(page, read.state, converterUrl);
}

export function wireSavedPage(): void {
  const page = document.querySelector<HTMLElement>("[data-local-saved-state-page]");
  if (!page) return;

  if (page.dataset.localStateWired !== "true") {
    page.dataset.localStateWired = "true";
    page
      .querySelector<HTMLFormElement>("[data-local-currency-form]")
      ?.addEventListener("submit", (event) => {
        event.preventDefault();
        const form = event.currentTarget as HTMLFormElement;
        const select = form.querySelector<HTMLSelectElement>("[name='currency_code']");
        const option = select?.selectedOptions[0];
        if (!select || !option || !select.value) return;
        const read = readState();
        if (read.status === "unavailable") return renderSavedPage();
        const normalized = normalizeSavedCurrency({
          code: select.value,
          name: option.dataset.currencyName ?? "",
          savedAt: new Date().toISOString(),
        });
        if (!normalized) return;
        if (read.state.currencies.some((item) => item.code === normalized.code)) {
          renderSavedPage(`${normalized.code} is already saved in this browser.`);
          return;
        }
        const toggled = toggleCurrencyInState(read.state, {
          code: normalized.code,
          name: normalized.name,
        });
        persistAndRender(toggled.state, `${normalized.code} saved in this browser.`);
      });
    page
      .querySelector<HTMLButtonElement>("[data-clear-currencies]")
      ?.addEventListener("click", () => {
        const read = readState();
        if (read.status === "unavailable") return renderSavedPage();
        persistAndRender(
          { ...read.state, currencies: [] },
          "Saved currencies cleared from this browser.",
        );
      });
    page
      .querySelector<HTMLButtonElement>("[data-import-local-currencies]")
      ?.addEventListener("click", async (event) => {
        const button = event.currentTarget as HTMLButtonElement;
        const status = page.querySelector<HTMLElement>(
          "[data-local-currency-migration-status]",
        );
        button.disabled = true;
        if (status) {
          status.textContent = "Importing browser-only currencies to your account…";
          status.setAttribute("aria-live", "polite");
        }
        try {
          const result = await importLocalCurrenciesToAccount();
          if (status) {
            status.textContent =
              result.importedCount === 0
                ? "There were no browser-only currencies to import."
                : result.localCleanupSucceeded
                  ? `Imported ${result.importedCount} currency shortcut${result.importedCount === 1 ? "" : "s"} and removed the confirmed local copies.`
                  : "Currencies were saved to your account, but the browser copies could not be cleared.";
          }
          if (result.importedCount > 0 && result.localCleanupSucceeded) {
            window.location.reload();
            return;
          }
        } catch {
          if (status) {
            status.textContent =
              "Import failed. Browser-only currencies are unchanged and can be retried.";
          }
        }
        renderSavedPage();
      });
    page
      .querySelector<HTMLButtonElement>("[data-clear-favourites]")
      ?.addEventListener("click", () => {
        const read = readState();
        if (read.status === "unavailable") return renderSavedPage();
        persistAndRender(
          { ...read.state, favourites: [] },
          "Saved pairs cleared from this browser.",
        );
      });
    page.querySelector<HTMLButtonElement>("[data-clear-places]")?.addEventListener("click", () => {
      const read = readState();
      if (read.status === "unavailable") return renderSavedPage();
      persistAndRender({ ...read.state, places: [] }, "Saved places cleared from this browser.");
    });
    page.querySelector<HTMLButtonElement>("[data-clear-recents]")?.addEventListener("click", () => {
      const read = readState();
      if (read.status === "unavailable") return renderSavedPage();
      const message =
        page.dataset.accountMode === "true"
          ? "Browser-only history cleared from this device."
          : "Recent history cleared from this browser.";
      persistAndRender({ ...read.state, recent: [] }, message);
    });
    page
      .querySelector<HTMLButtonElement>("[data-import-local-places]")
      ?.addEventListener("click", async (event) => {
        const button = event.currentTarget as HTMLButtonElement;
        const status = page.querySelector<HTMLElement>("[data-local-place-migration-status]");
        button.disabled = true;
        if (status) {
          status.textContent = "Importing browser-only places to your account…";
          status.setAttribute("aria-live", "polite");
        }

        try {
          const result = await importLocalPlacesToAccount();
          if (status) {
            status.textContent =
              result.importedCount === 0
                ? "There were no browser-only places to import."
                : result.localCleanupSucceeded
                  ? `Imported ${result.importedCount} browser-only place${result.importedCount === 1 ? "" : "s"} to your account and removed the confirmed local copies.`
                  : `Imported ${result.importedCount} browser-only place${result.importedCount === 1 ? "" : "s"} to your account. The browser copies could not be cleared, so they remain safely on this device.`;
          }
          if (result.importedCount > 0 && result.localCleanupSucceeded) {
            window.location.reload();
            return;
          }
        } catch {
          if (status) {
            status.textContent =
              "Import failed. Your browser-only places are unchanged and can be retried.";
          }
        }
        renderSavedPage();
      });
  }

  renderSavedPage();
}
