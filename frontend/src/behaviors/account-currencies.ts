import { readState, type SavedCurrency, writeState } from "./local-saved-state-store";

interface AccountCurrencySyncConfig {
  url: string;
  csrfToken: string;
}

function config(): AccountCurrencySyncConfig | null {
  const {
    accountAuthenticated,
    accountCurrencySyncUrl: url,
    accountCsrfToken: csrfToken,
  } = document.body.dataset;
  if (accountAuthenticated !== "true" || !url || !csrfToken) return null;
  return { url, csrfToken };
}

export function accountCurrencySyncAvailable(): boolean {
  return config() !== null;
}

async function postCurrencies(
  codes: string[],
): Promise<{ createdCount: number; savedCount: number }> {
  const current = config();
  if (!current) throw new Error("Account currency sync is not available.");

  const response = await fetch(current.url, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": current.csrfToken,
    },
    body: JSON.stringify({ currencies: codes }),
  });
  if (!response.ok) {
    throw new Error(`Saved-currency sync failed with status ${response.status}.`);
  }
  return (await response.json()) as { createdCount: number; savedCount: number };
}

export async function importLocalCurrenciesToAccount(): Promise<{
  importedCount: number;
  createdCount: number;
  localCleanupSucceeded: boolean;
}> {
  const read = readState();
  if (read.status === "unavailable" || read.state.currencies.length === 0) {
    return { importedCount: 0, createdCount: 0, localCleanupSucceeded: true };
  }

  const snapshot: SavedCurrency[] = [...read.state.currencies];
  const response = await postCurrencies(snapshot.map((item) => item.code));
  const latest = readState();
  let localCleanupSucceeded = false;
  if (latest.status !== "unavailable") {
    const imported = new Set(snapshot.map((item) => item.code));
    localCleanupSucceeded = writeState({
      ...latest.state,
      currencies: latest.state.currencies.filter((item) => !imported.has(item.code)),
    });
  }

  return {
    importedCount: snapshot.length,
    createdCount: response.createdCount,
    localCleanupSucceeded,
  };
}
