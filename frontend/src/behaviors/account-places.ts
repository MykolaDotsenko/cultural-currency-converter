import {
  readState,
  type SavedPlace,
  writeState,
} from "./local-saved-state-store";

interface AccountPlaceSyncConfig {
  url: string;
  stateUrl: string;
  csrfToken: string;
}

interface AccountPlaceSyncResponse {
  createdCount: number;
  savedCount: number;
}

function accountPlaceSyncConfig(): AccountPlaceSyncConfig | null {
  const {
    accountAuthenticated,
    accountPlaceSyncUrl: url,
    accountPlaceStateUrl: stateUrl,
    accountCsrfToken: csrfToken,
  } = document.body.dataset;
  if (accountAuthenticated !== "true" || !url || !stateUrl || !csrfToken) return null;
  return { url, stateUrl, csrfToken };
}

export function accountPlaceSyncAvailable(): boolean {
  return accountPlaceSyncConfig() !== null;
}

let accountPlaceTokensPromise: Promise<Set<string>> | null = null;

export function loadAccountSavedPlaceTokens(): Promise<Set<string>> {
  if (accountPlaceTokensPromise) return accountPlaceTokensPromise;

  const config = accountPlaceSyncConfig();
  if (!config) return Promise.resolve(new Set());

  accountPlaceTokensPromise = fetch(config.stateUrl, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  })
    .then(async (response) => {
      if (!response.ok) {
        throw new Error(`Saved-place state failed with status ${response.status}.`);
      }
      const payload = (await response.json()) as { tokens?: unknown };
      if (
        !Array.isArray(payload.tokens) ||
        payload.tokens.some((token) => typeof token !== "string")
      ) {
        throw new Error("Saved-place state response is invalid.");
      }
      return new Set(payload.tokens);
    })
    .catch((error: unknown) => {
      accountPlaceTokensPromise = null;
      throw error;
    });

  return accountPlaceTokensPromise;
}

function invalidateAccountPlaceTokenCache(): void {
  accountPlaceTokensPromise = null;
}

function placePayload(place: Pick<SavedPlace, "countryCode" | "citySlug">) {
  return {
    countryCode: place.countryCode,
    citySlug: place.citySlug,
  };
}

async function postPlaces(
  places: Array<Pick<SavedPlace, "countryCode" | "citySlug">>,
): Promise<AccountPlaceSyncResponse> {
  const config = accountPlaceSyncConfig();
  if (!config) throw new Error("Account place sync is not available.");

  const response = await fetch(config.url, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": config.csrfToken,
    },
    body: JSON.stringify({ places: places.map(placePayload) }),
  });
  if (!response.ok) {
    throw new Error(`Saved-place sync failed with status ${response.status}.`);
  }
  return (await response.json()) as AccountPlaceSyncResponse;
}

export async function savePlaceToAccount(
  place: Pick<SavedPlace, "countryCode" | "citySlug">,
): Promise<boolean> {
  const response = await postPlaces([place]);
  invalidateAccountPlaceTokenCache();
  return response.createdCount > 0;
}

export async function importLocalPlacesToAccount(): Promise<{
  importedCount: number;
  createdCount: number;
  localCleanupSucceeded: boolean;
}> {
  const read = readState();
  if (read.status === "unavailable" || read.state.places.length === 0) {
    return { importedCount: 0, createdCount: 0, localCleanupSucceeded: true };
  }

  const snapshot = [...read.state.places];
  const response = await postPlaces(snapshot);
  invalidateAccountPlaceTokenCache();

  // Clear only the exact local records that were confirmed by the server.
  // Concurrent/new browser-only saves remain local and can be imported later.
  const latest = readState();
  let localCleanupSucceeded = false;
  if (latest.status !== "unavailable") {
    const importedTokens = new Set(snapshot.map((item) => item.token));
    localCleanupSucceeded = writeState({
      ...latest.state,
      places: latest.state.places.filter((item) => !importedTokens.has(item.token)),
    });
  }

  return {
    importedCount: snapshot.length,
    createdCount: response.createdCount,
    localCleanupSucceeded,
  };
}
