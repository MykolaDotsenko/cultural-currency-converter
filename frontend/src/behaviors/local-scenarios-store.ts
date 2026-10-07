const STORAGE_VERSION = 1 as const;
const MAX_SCENARIOS = 10;
const STORAGE_PROBE_KEY = "cultural-currency:local-scenarios-probe";

export const LOCAL_SCENARIOS_KEY = "cultural-currency:local-scenarios:v1";

export type LocalScenarioKind = "budget" | "shopping";
export type LocalScenarioReadStatus = "ok" | "recovered" | "unavailable";

export interface LocalScenarioSummary {
  id: string;
  kind: LocalScenarioKind;
  title: string;
  scopeLabel: string;
  sourceAmount: string;
  sourceCurrency: string;
  destinationCurrency: string;
  durationDays: number | null;
  travelers: number;
  effectiveDate: string;
  stale: boolean;
}

export interface LocalScenarioRecord extends LocalScenarioSummary {
  token: string;
  savedAt: string;
}

interface LocalScenarioStoreV1 {
  version: typeof STORAGE_VERSION;
  scenarios: LocalScenarioRecord[];
}

export interface LocalScenarioReadResult {
  state: LocalScenarioStoreV1;
  status: LocalScenarioReadStatus;
}

let cachedStorage: Storage | null | undefined;

function emptyState(): LocalScenarioStoreV1 {
  return { version: STORAGE_VERSION, scenarios: [] };
}

function storageOrNull(): Storage | null {
  if (cachedStorage !== undefined) return cachedStorage;
  try {
    const storage = window.localStorage;
    storage.setItem(STORAGE_PROBE_KEY, "1");
    storage.removeItem(STORAGE_PROBE_KEY);
    cachedStorage = storage;
  } catch {
    cachedStorage = null;
  }
  return cachedStorage;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function boundedString(value: unknown, maxLength: number): string | null {
  return typeof value === "string" && value.length <= maxLength ? value : null;
}

function requiredString(value: unknown, maxLength: number): string | null {
  const text = boundedString(value, maxLength);
  return text !== null && text.trim().length > 0 ? text : null;
}

function currencyCode(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const code = value.toUpperCase();
  return /^[A-Z]{3}$/.test(code) ? code : null;
}

function decimalText(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 80) return null;
  return /^\d+(?:\.\d+)?$/.test(value) ? value : null;
}

function uuidText(value: unknown): string | null {
  if (typeof value !== "string") return null;
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value,
  )
    ? value.toLowerCase()
    : null;
}

function isoDate(value: unknown): string | null {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  return Number.isNaN(Date.parse(`${value}T00:00:00Z`)) ? null : value;
}

function timestamp(value: unknown): string | null {
  return typeof value === "string" && !Number.isNaN(Date.parse(value)) ? value : null;
}

function duration(value: unknown): number | null | undefined {
  if (value === null) return null;
  if (!Number.isInteger(value) || typeof value !== "number" || value < 1 || value > 365) {
    return undefined;
  }
  return value;
}

function travelers(value: unknown): number | null {
  if (!Number.isInteger(value) || typeof value !== "number" || value < 1 || value > 20) {
    return null;
  }
  return value;
}

function scenarioKind(value: unknown): LocalScenarioKind | null {
  return value === "budget" || value === "shopping" ? value : null;
}

export function normalizeLocalScenario(value: unknown): LocalScenarioRecord | null {
  if (!isRecord(value)) return null;

  const id = uuidText(value.id);
  const kind = scenarioKind(value.kind);
  const title = requiredString(value.title, 120);
  const scopeLabel = requiredString(value.scopeLabel, 160);
  const sourceAmount = decimalText(value.sourceAmount);
  const sourceCurrency = currencyCode(value.sourceCurrency);
  const destinationCurrency = currencyCode(value.destinationCurrency);
  const durationDays = duration(value.durationDays);
  const travelerCount = travelers(value.travelers);
  const effectiveDate = isoDate(value.effectiveDate);
  const token = requiredString(value.token, 16_384);
  const savedAt = timestamp(value.savedAt);

  if (
    id === null ||
    kind === null ||
    title === null ||
    scopeLabel === null ||
    sourceAmount === null ||
    sourceCurrency === null ||
    destinationCurrency === null ||
    durationDays === undefined ||
    travelerCount === null ||
    effectiveDate === null ||
    typeof value.stale !== "boolean" ||
    token === null ||
    savedAt === null
  ) {
    return null;
  }

  if (kind === "budget" && durationDays === null) return null;
  if (kind === "shopping" && (durationDays !== null || travelerCount !== 1)) return null;

  return {
    id,
    kind,
    title,
    scopeLabel,
    sourceAmount,
    sourceCurrency,
    destinationCurrency,
    durationDays,
    travelers: travelerCount,
    effectiveDate,
    stale: value.stale,
    token,
    savedAt,
  };
}

export function readLocalScenarios(): LocalScenarioReadResult {
  const storage = storageOrNull();
  if (!storage) return { state: emptyState(), status: "unavailable" };

  const raw = storage.getItem(LOCAL_SCENARIOS_KEY);
  if (!raw) return { state: emptyState(), status: "ok" };

  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!isRecord(parsed) || parsed.version !== STORAGE_VERSION || !Array.isArray(parsed.scenarios)) {
      storage.removeItem(LOCAL_SCENARIOS_KEY);
      return { state: emptyState(), status: "recovered" };
    }

    const seen = new Set<string>();
    const scenarios: LocalScenarioRecord[] = [];
    for (const item of parsed.scenarios) {
      const normalized = normalizeLocalScenario(item);
      if (!normalized || seen.has(normalized.id)) continue;
      seen.add(normalized.id);
      scenarios.push(normalized);
      if (scenarios.length >= MAX_SCENARIOS) break;
    }

    const recovered =
      scenarios.length !== Math.min(parsed.scenarios.length, MAX_SCENARIOS) ||
      parsed.scenarios.length > MAX_SCENARIOS;
    const state = { version: STORAGE_VERSION, scenarios };
    if (recovered) storage.setItem(LOCAL_SCENARIOS_KEY, JSON.stringify(state));
    return { state, status: recovered ? "recovered" : "ok" };
  } catch {
    storage.removeItem(LOCAL_SCENARIOS_KEY);
    return { state: emptyState(), status: "recovered" };
  }
}

export function writeLocalScenarios(state: LocalScenarioStoreV1): boolean {
  const storage = storageOrNull();
  if (!storage) return false;
  try {
    storage.setItem(LOCAL_SCENARIOS_KEY, JSON.stringify(state));
    return true;
  } catch {
    return false;
  }
}

export function localScenarioStorageAvailable(): boolean {
  return storageOrNull() !== null;
}

export function saveLocalScenario(
  summary: LocalScenarioSummary,
  token: string,
  savedAt = new Date().toISOString(),
): { state: LocalScenarioStoreV1; record: LocalScenarioRecord } | null {
  const normalized = normalizeLocalScenario({ ...summary, token, savedAt });
  if (!normalized) return null;

  const read = readLocalScenarios();
  if (read.status === "unavailable") return null;

  const scenarios = [
    normalized,
    ...read.state.scenarios.filter((item) => item.id !== normalized.id),
  ].slice(0, MAX_SCENARIOS);
  const state = { version: STORAGE_VERSION, scenarios };
  return writeLocalScenarios(state) ? { state, record: normalized } : null;
}

export function removeLocalScenario(id: string): boolean {
  const read = readLocalScenarios();
  if (read.status === "unavailable") return false;
  return writeLocalScenarios({
    version: STORAGE_VERSION,
    scenarios: read.state.scenarios.filter((item) => item.id !== id),
  });
}

export function removeImportedLocalScenarios(ids: ReadonlySet<string>): boolean {
  const read = readLocalScenarios();
  if (read.status === "unavailable") return false;
  return writeLocalScenarios({
    version: STORAGE_VERSION,
    scenarios: read.state.scenarios.filter((item) => !ids.has(item.id)),
  });
}

export function clearLocalScenarios(): boolean {
  return writeLocalScenarios(emptyState());
}
