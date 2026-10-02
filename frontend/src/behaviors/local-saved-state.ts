import {
  accountFavouriteSyncAvailable,
  saveFavouriteToAccount,
  syncLocalFavouritesToAccount,
} from "./account-favourites";
import { wireSavedPage } from "./local-saved-state-page";
import {
  isFavourite,
  isPlaceSaved,
  type LocalPreferencesV1,
  normalizePair,
  normalizePlace,
  normalizeRecent,
  type PairContext,
  type ReadStatus,
  readState,
  type SavedPlace,
  STORAGE_KEY,
  toggleFavouriteInState,
  togglePlaceInState,
  upsertRecent,
  writeState,
} from "./local-saved-state-store";


function pairFromSnapshot(element: HTMLElement): PairContext | null {
  return normalizePair({
    sourceCurrency: element.dataset.sourceCurrency ?? "",
    destinationCurrency: element.dataset.destinationCurrency ?? "",
    sourceCountry: element.dataset.sourceCountry ?? "",
    destinationCountry: element.dataset.destinationCountry ?? "",
    sourceCountryName: element.dataset.sourceCountryName ?? "",
    destinationCountryName: element.dataset.destinationCountryName ?? "",
  });
}

function recentFromSnapshot(element: HTMLElement) {
  return normalizeRecent({
    sourceCurrency: element.dataset.sourceCurrency ?? "",
    destinationCurrency: element.dataset.destinationCurrency ?? "",
    sourceCountry: element.dataset.sourceCountry ?? "",
    destinationCountry: element.dataset.destinationCountry ?? "",
    sourceCountryName: element.dataset.sourceCountryName ?? "",
    destinationCountryName: element.dataset.destinationCountryName ?? "",
    amount: element.dataset.inputAmount ?? "",
    outputAmount: element.dataset.outputAmount ?? "",
    rateMode: element.dataset.rateMode ?? "",
    requestedDate: element.dataset.requestedDate ?? "",
    effectiveDate: element.dataset.effectiveDate ?? "",
    convertedAt: new Date().toISOString(),
  });
}

function addRecent(snapshot: HTMLElement): void {
  const recent = recentFromSnapshot(snapshot);
  if (!recent) return;

  const read = readState();
  if (read.status === "unavailable") return;
  writeState(upsertRecent(read.state, recent));
}

function setAnonymousFavouriteButtonState(
  snapshot: HTMLElement,
  state: LocalPreferencesV1,
  storageStatus: ReadStatus,
): void {
  const button = snapshot.querySelector<HTMLButtonElement>("[data-save-pair]");
  const label = snapshot.querySelector<HTMLElement>("[data-save-pair-label]");
  const pair = pairFromSnapshot(snapshot);
  if (!button || !label || !pair) return;

  button.hidden = false;
  const saved = isFavourite(pair, state);
  button.setAttribute("aria-pressed", saved ? "true" : "false");
  button.setAttribute("aria-label", saved ? "Remove saved pair" : "Save pair");
  button.dataset.saved = saved ? "true" : "false";
  label.textContent = saved ? "Saved" : "Save pair";

  if (storageStatus === "unavailable") button.dataset.storageUnavailable = "true";
  else delete button.dataset.storageUnavailable;
}

function setAccountFavouriteButtonState(snapshot: HTMLElement, saved: boolean): void {
  const button = snapshot.querySelector<HTMLButtonElement>("[data-save-pair]");
  const label = snapshot.querySelector<HTMLElement>("[data-save-pair-label]");
  if (!button || !label) return;

  button.removeAttribute("aria-pressed");
  button.setAttribute("aria-label", saved ? "Pair saved to account" : "Save pair to account");
  button.dataset.saved = saved ? "true" : "false";
  button.disabled = saved;
  delete button.dataset.storageUnavailable;
  label.textContent = saved ? "Saved to account" : "Save to account";
}

function saveStatus(snapshot: HTMLElement, message: string): void {
  const status = snapshot.querySelector<HTMLElement>("[data-save-pair-status]");
  if (status) status.textContent = message;
}

async function saveAccountFavourite(snapshot: HTMLElement): Promise<void> {
  const pair = pairFromSnapshot(snapshot);
  const button = snapshot.querySelector<HTMLButtonElement>("[data-save-pair]");
  if (!pair || !button) return;

  button.disabled = true;
  saveStatus(snapshot, "Saving pair to your account…");
  try {
    const created = await saveFavouriteToAccount(pair);
    snapshot.dataset.accountSaved = "true";
    setAccountFavouriteButtonState(snapshot, true);
    saveStatus(
      snapshot,
      created ? "Saved to your account." : "This pair is already saved to your account.",
    );
  } catch {
    saveStatus(
      snapshot,
      "The pair could not be saved to your account. Your conversion is unchanged.",
    );
  } finally {
    button.disabled = snapshot.dataset.accountSaved === "true";
  }
}

function toggleAnonymousFavourite(snapshot: HTMLElement): void {
  const pair = pairFromSnapshot(snapshot);
  if (!pair) return;

  const read = readState();
  if (read.status === "unavailable") {
    saveStatus(
      snapshot,
      "Saved pairs are unavailable because browser storage is blocked. Conversion still works.",
    );
    setAnonymousFavouriteButtonState(snapshot, read.state, read.status);
    return;
  }

  const toggled = toggleFavouriteInState(read.state, pair);
  if (!writeState(toggled.state)) {
    saveStatus(snapshot, "The pair could not be saved because browser storage is unavailable.");
    return;
  }

  setAnonymousFavouriteButtonState(snapshot, toggled.state, "ok");
  saveStatus(snapshot, toggled.saved ? "Saved in this browser." : "Removed from saved.");
}

function placeFromSurface(surface: HTMLElement): Omit<SavedPlace, "id" | "savedAt"> | null {
  const normalized = normalizePlace({
    countryCode: surface.dataset.placeCountryCode ?? "",
    countryName: surface.dataset.placeCountryName ?? "",
    citySlug: surface.dataset.placeCitySlug ?? "",
    cityName: surface.dataset.placeCityName ?? "",
    currencyCode: surface.dataset.placeCurrencyCode ?? "",
    savedAt: new Date().toISOString(),
  });
  if (!normalized || normalized.token !== surface.dataset.placeToken) return null;

  return {
    token: normalized.token,
    countryCode: normalized.countryCode,
    countryName: normalized.countryName,
    citySlug: normalized.citySlug,
    cityName: normalized.cityName,
    currencyCode: normalized.currencyCode,
  };
}

function placeStatus(surface: HTMLElement, message: string): void {
  const status = surface.querySelector<HTMLElement>("[data-save-place-status]");
  if (status) status.textContent = message;
}

function setPlaceSurfaceState(
  surface: HTMLElement,
  state: LocalPreferencesV1,
  storageStatus: ReadStatus,
): void {
  const button = surface.querySelector<HTMLButtonElement>("[data-save-place]");
  const label = surface.querySelector<HTMLElement>("[data-save-place-label]");
  const place = placeFromSurface(surface);
  if (!button || !label || !place) {
    if (button) button.hidden = true;
    return;
  }

  const placeName = place.cityName ? `${place.cityName}, ${place.countryName}` : place.countryName;
  if (storageStatus === "unavailable") {
    button.hidden = true;
    return;
  }

  button.hidden = false;
  const saved = isPlaceSaved(place.token, state);
  button.disabled = false;
  button.setAttribute("aria-pressed", saved ? "true" : "false");
  button.setAttribute(
    "aria-label",
    saved ? `Remove saved place: ${placeName}` : `Save place: ${placeName}`,
  );
  button.dataset.saved = saved ? "true" : "false";
  label.textContent = saved ? "Saved" : "Save";
}

function toggleSavedPlace(surface: HTMLElement): void {
  const place = placeFromSurface(surface);
  const button = surface.querySelector<HTMLButtonElement>("[data-save-place]");
  if (!place || !button) return;

  const read = readState();
  if (read.status === "unavailable") {
    setPlaceSurfaceState(surface, read.state, read.status);
    placeStatus(surface, "My places is unavailable because browser storage is blocked.");
    return;
  }

  const toggled = togglePlaceInState(read.state, place);
  if (!writeState(toggled.state)) {
    setPlaceSurfaceState(surface, read.state, "unavailable");
    placeStatus(surface, "Place could not be saved because browser storage is unavailable.");
    return;
  }

  enhanceExploreSavedPlaces();
  placeStatus(
    surface,
    toggled.saved ? "Place saved in this browser." : "Place removed from this browser.",
  );
}

function enhanceExploreSavedPlaces(): void {
  const surfaces = document.querySelectorAll<HTMLElement>("[data-local-saved-place]");
  if (surfaces.length === 0) return;

  const read = readState();
  for (const surface of surfaces) {
    setPlaceSurfaceState(surface, read.state, read.status);
    if (surface.dataset.savePlaceWired === "true") continue;

    const button = surface.querySelector<HTMLButtonElement>("[data-save-place]");
    if (!button) continue;

    surface.dataset.savePlaceWired = "true";
    button.addEventListener("click", () => toggleSavedPlace(surface));
  }
}

function enhanceConversionSnapshots(): void {
  const read = readState();
  const accountMode = accountFavouriteSyncAvailable();

  for (const snapshot of document.querySelectorAll<HTMLElement>(
    "[data-local-conversion-snapshot]",
  )) {
    if (accountMode) {
      setAccountFavouriteButtonState(snapshot, snapshot.dataset.accountSaved === "true");
    } else {
      setAnonymousFavouriteButtonState(snapshot, read.state, read.status);
    }

    if (snapshot.dataset.localStateWired !== "true") {
      snapshot.dataset.localStateWired = "true";
      snapshot
        .querySelector<HTMLButtonElement>("[data-save-pair]")
        ?.addEventListener("click", () => {
          if (accountMode) void saveAccountFavourite(snapshot);
          else toggleAnonymousFavourite(snapshot);
        });
    }

    if (snapshot.dataset.recentRecorded !== "true") {
      snapshot.dataset.recentRecorded = "true";
      if (snapshot.dataset.accountRecentRecorded !== "true") addRecent(snapshot);
    }
  }
}

function enhanceSavedPage(): void {
  const page = document.querySelector<HTMLElement>("[data-local-saved-state-page]");
  if (!page) return;

  const status = page.querySelector<HTMLElement>("[data-local-storage-status]");
  if (status) status.hidden = false;
  wireSavedPage();
}

function syncLocalAccountFavourites(): void {
  if (!accountFavouriteSyncAvailable()) return;

  void syncLocalFavouritesToAccount()
    .then((mergedCount) => {
      if (
        mergedCount > 0 &&
        document.querySelector<HTMLElement>(
          '[data-local-saved-state-page][data-account-mode="true"]',
        )
      ) {
        window.location.reload();
      }
    })
    .catch((error: unknown) => {
      console.error("Local favourites could not be merged into the account.", error);
      const status = document.querySelector<HTMLElement>("[data-local-storage-status]");
      if (status) {
        status.hidden = false;
        status.dataset.storageTone = "warning";
        status.setAttribute("aria-live", "polite");
        status.textContent =
          "Your browser-local saved pairs could not be synced. They remain on this device.";
      }
    });
}

export function enhanceLocalSavedState(): void {
  enhanceConversionSnapshots();
  enhanceExploreSavedPlaces();
  enhanceSavedPage();
  syncLocalAccountFavourites();
}

document.addEventListener("DOMContentLoaded", enhanceLocalSavedState);
document.addEventListener("htmx:afterSwap", enhanceLocalSavedState);
window.addEventListener("storage", (event) => {
  if (event.key === STORAGE_KEY) enhanceLocalSavedState();
});
