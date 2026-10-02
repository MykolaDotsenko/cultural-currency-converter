import {
  readState,
  type SavedPlace,
  writeState,
} from "./local-saved-state-store";

interface AccountPlaceSyncConfig {
  url: string;
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
    accountCsrfToken: csrfToken,
  } = document.body.dataset;
  if (accountAuthenticated !== "true" || !url || !csrfToken) return null;
  return { url, csrfToken };
}

export function accountPlaceSyncAvailable(): boolean {
  return accountPlaceSyncConfig() !== null;
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
  return response.createdCount > 0;
}

export async function importLocalPlacesToAccount(): Promise<{
  importedCount: number;
  createdCount: number;
}> {
  const read = readState();
  if (read.status === "unavailable" || read.state.places.length === 0) {
    return { importedCount: 0, createdCount: 0 };
  }

  const snapshot = [...read.state.places];
  const response = await postPlaces(snapshot);

  // Clear only the exact local records that were confirmed by the server.
  // Concurrent/new browser-only saves remain local and can be imported later.
  const latest = readState();
  if (latest.status !== "unavailable") {
    const importedTokens = new Set(snapshot.map((item) => item.token));
    writeState({
      ...latest.state,
      places: latest.state.places.filter((item) => !importedTokens.has(item.token)),
    });
  }

  return {
    importedCount: snapshot.length,
    createdCount: response.createdCount,
  };
}
