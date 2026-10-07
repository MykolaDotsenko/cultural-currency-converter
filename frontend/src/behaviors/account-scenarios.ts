import { readState, writeState } from "./local-saved-state-store";

interface ScenarioImportResponse {
  importedOriginKeys: string[];
  createdCount: number;
  savedCount: number;
}

interface ScenarioImportConfig {
  url: string;
  csrfToken: string;
}

function config(): ScenarioImportConfig | null {
  const {
    accountAuthenticated,
    accountScenarioImportUrl: url,
    accountCsrfToken: csrfToken,
  } = document.body.dataset;
  if (accountAuthenticated !== "true" || !url || !csrfToken) return null;
  return { url, csrfToken };
}

export function accountScenarioImportAvailable(): boolean {
  return config() !== null;
}

export async function importLocalScenariosToAccount(): Promise<{
  importedCount: number;
  createdCount: number;
  localCleanupSucceeded: boolean;
}> {
  const current = config();
  if (!current) throw new Error("Account scenario import is not available.");

  const read = readState();
  if (read.status === "unavailable" || read.state.scenarios.length === 0) {
    return { importedCount: 0, createdCount: 0, localCleanupSucceeded: true };
  }

  const snapshot = [...read.state.scenarios];
  const response = await fetch(current.url, {
    method: "POST",
    credentials: "same-origin",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": current.csrfToken,
    },
    body: JSON.stringify({ scenarios: snapshot.map((item) => item.token) }),
  });
  if (!response.ok) {
    let message = "Browser scenarios could not be imported.";
    try {
      const payload = (await response.json()) as { error?: { message?: string } };
      if (payload.error?.message) message = payload.error.message;
    } catch {
      // Keep the safe generic message.
    }
    throw new Error(message);
  }

  const payload = (await response.json()) as ScenarioImportResponse;
  const imported = new Set(payload.importedOriginKeys);
  if (
    !Array.isArray(payload.importedOriginKeys) ||
    payload.importedOriginKeys.some((value) => typeof value !== "string")
  ) {
    throw new Error("Scenario import returned an invalid confirmation.");
  }

  const latest = readState();
  let localCleanupSucceeded = false;
  if (latest.status !== "unavailable") {
    localCleanupSucceeded = writeState({
      ...latest.state,
      scenarios: latest.state.scenarios.filter((item) => !imported.has(item.id)),
    });
  }

  return {
    importedCount: imported.size,
    createdCount: payload.createdCount,
    localCleanupSucceeded,
  };
}
