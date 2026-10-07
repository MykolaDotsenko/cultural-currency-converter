const STORAGE_VERSION = 1 as const;
const MAX_FAVOURITES = 12;
const MAX_RECENTS = 10;
const MAX_PLACES = 24;
const MAX_CURRENCIES = 24;
const MAX_SCENARIOS = 12;
const STORAGE_PROBE_KEY = "cultural-currency:storage-probe";

export const STORAGE_KEY = "cultural-currency:local-preferences:v1";

export type RateMode = "latest" | "historical";
export type ReadStatus = "ok" | "recovered" | "unavailable";

export interface PairContext {
  sourceCurrency: string;
  destinationCurrency: string;
  sourceCountry: string;
  destinationCountry: string;
  sourceCountryName: string;
  destinationCountryName: string;
}

export interface FavouritePair extends PairContext {
  id: string;
  savedAt: string;
}

export interface SavedPlace {
  id: string;
  token: string;
  countryCode: string;
  countryName: string;
  citySlug: string;
  cityName: string;
  currencyCode: string;
  savedAt: string;
}

export interface SavedCurrency {
  id: string;
  code: string;
  name: string;
  savedAt: string;
}

export interface BrowserScenario {
  id: string;
  token: string;
  kind: "budget" | "shopping";
  title: string;
  scope: string;
  sourceCurrency: string;
  destinationCurrency: string;
  sourceAmount: string;
  savedAt: string;
  reopenUrl: string;
}

export interface RecentConversion extends PairContext {
  id: string;
  amount: string;
  outputAmount: string;
  rateMode: RateMode;
  requestedDate: string;
  effectiveDate: string;
  convertedAt: string;
}

export interface LocalPreferencesV1 {
  version: typeof STORAGE_VERSION;
  favourites: FavouritePair[];
  places: SavedPlace[];
  currencies: SavedCurrency[];
  scenarios: BrowserScenario[];
  recent: RecentConversion[];
}

export interface ReadResult {
  state: LocalPreferencesV1;
  status: ReadStatus;
}

let cachedStorage: Storage | null | undefined;

function emptyState(): LocalPreferencesV1 {
  return {
    version: STORAGE_VERSION,
    favourites: [],
    places: [],
    currencies: [],
    scenarios: [],
    recent: [],
  };
}

function localStorageOrNull(): Storage | null {
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

function normalizedString(value: unknown, maxLength: number): string | null {
  return typeof value === "string" && value.length <= maxLength ? value : null;
}

function normalizedCurrencyCode(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const code = value.toUpperCase();
  return /^[A-Z]{3}$/.test(code) ? code : null;
}

function normalizedCountryCode(value: unknown): string | null {
  if (value === "") return "";
  if (typeof value !== "string") return null;
  const code = value.toUpperCase();
  return /^[A-Z]{2}$/.test(code) ? code : null;
}

function normalizedIsoDate(value: unknown, allowEmpty = false): string | null {
  if (allowEmpty && value === "") return "";
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  return Number.isNaN(Date.parse(`${value}T00:00:00Z`)) ? null : value;
}

function normalizedTimestamp(value: unknown): string | null {
  return typeof value === "string" && !Number.isNaN(Date.parse(value)) ? value : null;
}

function normalizedAmount(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 64) return null;
  return /^\d+(?:\.\d+)?$/.test(value) ? value : null;
}

function normalizedRelativeUrl(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 2048) return null;
  return /^\/(?!\/)[^\s]*$/.test(value) ? value : null;
}

export function normalizePair(value: Record<string, unknown>): PairContext | null {
  const sourceCurrency = normalizedCurrencyCode(value.sourceCurrency);
  const destinationCurrency = normalizedCurrencyCode(value.destinationCurrency);
  const sourceCountry = normalizedCountryCode(value.sourceCountry);
  const destinationCountry = normalizedCountryCode(value.destinationCountry);
  const sourceCountryName = normalizedString(value.sourceCountryName, 120);
  const destinationCountryName = normalizedString(value.destinationCountryName, 120);

  if (
    sourceCurrency === null ||
    destinationCurrency === null ||
    sourceCountry === null ||
    destinationCountry === null ||
    sourceCountryName === null ||
    destinationCountryName === null
  ) {
    return null;
  }

  return {
    sourceCurrency,
    destinationCurrency,
    sourceCountry,
    destinationCountry,
    sourceCountryName,
    destinationCountryName,
  };
}

export function pairId(pair: PairContext): string {
  return [
    pair.sourceCountry || "_",
    pair.sourceCurrency,
    ">",
    pair.destinationCountry || "_",
    pair.destinationCurrency,
  ].join(":");
}

function normalizedCitySlug(value: unknown): string | null {
  if (value === "") return "";
  if (typeof value !== "string" || value.length > 120) return null;
  const slug = value.toLowerCase().trim();
  return /^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(slug) ? slug : null;
}

export function normalizePlace(value: unknown): SavedPlace | null {
  if (!isRecord(value)) return null;
  const countryCode = normalizedCountryCode(value.countryCode);
  const countryName = normalizedString(value.countryName, 120);
  const citySlug = normalizedCitySlug(value.citySlug);
  const cityName = normalizedString(value.cityName, 120);
  const currencyCode = normalizedCurrencyCode(value.currencyCode);
  const savedAt = normalizedTimestamp(value.savedAt);
  if (
    !countryCode ||
    countryName === null ||
    citySlug === null ||
    cityName === null ||
    currencyCode === null ||
    savedAt === null
  ) {
    return null;
  }
  const token = citySlug ? `${countryCode}:${citySlug}` : countryCode;
  return {
    id: token,
    token,
    countryCode,
    countryName,
    citySlug,
    cityName,
    currencyCode,
    savedAt,
  };
}

export function normalizeSavedCurrency(value: unknown): SavedCurrency | null {
  if (!isRecord(value)) return null;
  const code = normalizedCurrencyCode(value.code);
  const name = normalizedString(value.name, 120);
  const savedAt = normalizedTimestamp(value.savedAt);
  if (code === null || name === null || savedAt === null) return null;
  return { id: code, code, name, savedAt };
}

export function normalizeBrowserScenario(value: unknown): BrowserScenario | null {
  if (!isRecord(value)) return null;
  const id =
    typeof value.id === "string" &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value.id)
      ? value.id.toLowerCase()
      : null;
  const token =
    typeof value.token === "string" && value.token.length > 0 && value.token.length <= 24_576
      ? value.token
      : null;
  const kind =
    value.kind === "budget" ? "budget" : value.kind === "shopping" ? "shopping" : null;
  const title = normalizedString(value.title, 120);
  const scope = normalizedString(value.scope, 160);
  const sourceCurrency = normalizedCurrencyCode(value.sourceCurrency);
  const destinationCurrency = normalizedCurrencyCode(value.destinationCurrency);
  const sourceAmount = normalizedAmount(value.sourceAmount);
  const savedAt = normalizedTimestamp(value.savedAt);
  const reopenUrl = normalizedRelativeUrl(value.reopenUrl);

  if (
    id === null ||
    token === null ||
    kind === null ||
    title === null ||
    scope === null ||
    sourceCurrency === null ||
    destinationCurrency === null ||
    sourceAmount === null ||
    savedAt === null ||
    reopenUrl === null
  ) {
    return null;
  }

  return {
    id,
    token,
    kind,
    title,
    scope,
    sourceCurrency,
    destinationCurrency,
    sourceAmount,
    savedAt,
    reopenUrl,
  };
}

function normalizeFavourite(value: unknown): FavouritePair | null {
  if (!isRecord(value)) return null;
  const pair = normalizePair(value);
  const savedAt = normalizedTimestamp(value.savedAt);
  if (!pair || savedAt === null) return null;
  return { ...pair, id: pairId(pair), savedAt };
}

function recentId(
  pair: PairContext,
  amount: string,
  rateMode: RateMode,
  requestedDate: string,
): string {
  return `${pairId(pair)}|${rateMode}|${requestedDate || "latest"}|${amount}`;
}

export function normalizeRecent(value: unknown): RecentConversion | null {
  if (!isRecord(value)) return null;
  const pair = normalizePair(value);
  const amount = normalizedAmount(value.amount);
  const outputAmount = normalizedAmount(value.outputAmount);
  const rateMode =
    value.rateMode === "historical" ? "historical" : value.rateMode === "latest" ? "latest" : null;
  const requestedDate = normalizedIsoDate(value.requestedDate, true);
  const effectiveDate = normalizedIsoDate(value.effectiveDate);
  const convertedAt = normalizedTimestamp(value.convertedAt);

  if (
    !pair ||
    amount === null ||
    outputAmount === null ||
    rateMode === null ||
    requestedDate === null ||
    effectiveDate === null ||
    convertedAt === null ||
    (rateMode === "historical" && requestedDate === "")
  ) {
    return null;
  }

  return {
    ...pair,
    id: recentId(pair, amount, rateMode, requestedDate),
    amount,
    outputAmount,
    rateMode,
    requestedDate,
    effectiveDate,
    convertedAt,
  };
}

function dedupeById<T extends { id: string }>(items: T[], limit: number): T[] {
  const seen = new Set<string>();
  const result: T[] = [];
  for (const item of items) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    result.push(item);
    if (result.length >= limit) break;
  }
  return result;
}

export function readState(): ReadResult {
  const storage = localStorageOrNull();
  if (!storage) return { state: emptyState(), status: "unavailable" };

  const raw = storage.getItem(STORAGE_KEY);
  if (raw === null) return { state: emptyState(), status: "ok" };

  try {
    const parsed: unknown = JSON.parse(raw);
    if (!isRecord(parsed) || parsed.version !== STORAGE_VERSION) {
      return { state: emptyState(), status: "recovered" };
    }

    const rawFavourites = Array.isArray(parsed.favourites) ? parsed.favourites : [];
    const rawPlaces = Array.isArray(parsed.places) ? parsed.places : [];
    const rawCurrencies = Array.isArray(parsed.currencies) ? parsed.currencies : [];
    const rawScenarios = Array.isArray(parsed.scenarios) ? parsed.scenarios : [];
    const rawRecent = Array.isArray(parsed.recent) ? parsed.recent : [];
    const favourites = dedupeById(
      rawFavourites.map(normalizeFavourite).filter((item): item is FavouritePair => item !== null),
      MAX_FAVOURITES,
    );
    const places = dedupeById(
      rawPlaces.map(normalizePlace).filter((item): item is SavedPlace => item !== null),
      MAX_PLACES,
    );
    const currencies = dedupeById(
      rawCurrencies
        .map(normalizeSavedCurrency)
        .filter((item): item is SavedCurrency => item !== null),
      MAX_CURRENCIES,
    );
    const scenarios = dedupeById(
      rawScenarios
        .map(normalizeBrowserScenario)
        .filter((item): item is BrowserScenario => item !== null),
      MAX_SCENARIOS,
    );
    const recent = dedupeById(
      rawRecent.map(normalizeRecent).filter((item): item is RecentConversion => item !== null),
      MAX_RECENTS,
    );
    const recovered =
      !Array.isArray(parsed.favourites) ||
      !Array.isArray(parsed.recent) ||
      favourites.length !== Math.min(rawFavourites.length, MAX_FAVOURITES) ||
      places.length !== Math.min(rawPlaces.length, MAX_PLACES) ||
      (parsed.currencies !== undefined && !Array.isArray(parsed.currencies)) ||
      currencies.length !== Math.min(rawCurrencies.length, MAX_CURRENCIES) ||
      (parsed.scenarios !== undefined && !Array.isArray(parsed.scenarios)) ||
      scenarios.length !== Math.min(rawScenarios.length, MAX_SCENARIOS) ||
      recent.length !== Math.min(rawRecent.length, MAX_RECENTS);

    return {
      state: { version: STORAGE_VERSION, favourites, places, currencies, scenarios, recent },
      status: recovered ? "recovered" : "ok",
    };
  } catch {
    return { state: emptyState(), status: "recovered" };
  }
}

export function writeState(state: LocalPreferencesV1): boolean {
  const storage = localStorageOrNull();
  if (!storage) return false;
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(state));
    return true;
  } catch {
    return false;
  }
}

export function isFavourite(pair: PairContext, state: LocalPreferencesV1): boolean {
  return state.favourites.some((item) => item.id === pairId(pair));
}

export function toggleFavouriteInState(
  state: LocalPreferencesV1,
  pair: PairContext,
  savedAt = new Date().toISOString(),
): { state: LocalPreferencesV1; saved: boolean } {
  const id = pairId(pair);
  const existed = state.favourites.some((item) => item.id === id);
  const favourites = existed
    ? state.favourites.filter((item) => item.id !== id)
    : [{ ...pair, id, savedAt }, ...state.favourites.filter((item) => item.id !== id)].slice(
        0,
        MAX_FAVOURITES,
      );

  return {
    state: { ...state, favourites },
    saved: !existed,
  };
}

export function isPlaceSaved(token: string, state: LocalPreferencesV1): boolean {
  return state.places.some((item) => item.token === token);
}

export function togglePlaceInState(
  state: LocalPreferencesV1,
  place: Omit<SavedPlace, "id" | "savedAt">,
  savedAt = new Date().toISOString(),
): { state: LocalPreferencesV1; saved: boolean } {
  const existed = state.places.some((item) => item.token === place.token);
  const places = existed
    ? state.places.filter((item) => item.token !== place.token)
    : [
        { ...place, id: place.token, savedAt },
        ...state.places.filter((item) => item.token !== place.token),
      ].slice(0, MAX_PLACES);
  return {
    state: { ...state, places },
    saved: !existed,
  };
}

export function isCurrencySaved(code: string, state: LocalPreferencesV1): boolean {
  return state.currencies.some((item) => item.code === code);
}

export function toggleCurrencyInState(
  state: LocalPreferencesV1,
  currency: Omit<SavedCurrency, "id" | "savedAt">,
  savedAt = new Date().toISOString(),
): { state: LocalPreferencesV1; saved: boolean } {
  const existed = state.currencies.some((item) => item.code === currency.code);
  const currencies = existed
    ? state.currencies.filter((item) => item.code !== currency.code)
    : [
        { ...currency, id: currency.code, savedAt },
        ...state.currencies.filter((item) => item.code !== currency.code),
      ].slice(0, MAX_CURRENCIES);
  return { state: { ...state, currencies }, saved: !existed };
}

export function upsertBrowserScenario(
  state: LocalPreferencesV1,
  scenario: BrowserScenario,
): LocalPreferencesV1 {
  return {
    ...state,
    scenarios: [
      scenario,
      ...state.scenarios.filter((item) => item.id !== scenario.id),
    ].slice(0, MAX_SCENARIOS),
  };
}

export function upsertRecent(
  state: LocalPreferencesV1,
  recent: RecentConversion,
): LocalPreferencesV1 {
  return {
    ...state,
    recent: [recent, ...state.recent.filter((item) => item.id !== recent.id)].slice(0, MAX_RECENTS),
  };
}
