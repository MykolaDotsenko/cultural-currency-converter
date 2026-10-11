/** Local-only, explicit trip input drafts. No FX, receipts or server-owned state. */
export const TRIP_DRAFT_KEY = "cultural-currency:trip-drafts:v1";
export const TRIP_HANDOFF_KEY = "cultural-currency:trip-draft-handoff:v1";
const VERSION = 1;
const MAX_DRAFTS = 8;
const MAX_SERIALIZED_BYTES = 16_384;

export interface TripDraft {
  id: string;
  title: string;
  destination: string;
  sourceCurrency: string;
  amount: string;
  travelers: number;
  durationDays: number;
  startDate: string;
  updatedAt: string;
}

interface DraftEnvelope {
  version: number;
  drafts: TripDraft[];
}
export type DraftRead =
  | { status: "ok"; drafts: TripDraft[] }
  | { status: "unavailable" | "invalid"; drafts: [] };
export type DraftStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function record(raw: unknown): raw is Record<string, unknown> {
  return raw !== null && typeof raw === "object" && !Array.isArray(raw);
}

function isoDay(raw: unknown): raw is string {
  if (typeof raw !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(raw)) return false;
  const date = new Date(`${raw}T00:00:00Z`);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === raw;
}

export function normalizeTripDraft(raw: unknown): TripDraft | null {
  if (!record(raw)) return null;
  const id = raw.id;
  const title = typeof raw.title === "string" ? raw.title.trim() : "";
  const destination = raw.destination;
  const sourceCurrency = raw.sourceCurrency;
  const amount = raw.amount;
  const travelers = raw.travelers;
  const durationDays = raw.durationDays;
  const startDate = raw.startDate;
  const updatedAt = raw.updatedAt;

  const containsControlCharacter = [...title].some((character) => {
    const code = character.charCodeAt(0);
    return code < 32 || code === 127;
  });
  if (
    typeof id !== "string" ||
    !/^[a-f0-9]{8}-[a-f0-9]{4}-[1-8][a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/i.test(id) ||
    !title ||
    title.length > 80 ||
    containsControlCharacter ||
    typeof destination !== "string" ||
    !/^[A-Z]{2}(?::[a-z0-9]+(?:-[a-z0-9]+)*)?$/.test(destination) ||
    typeof sourceCurrency !== "string" ||
    !/^[A-Z]{3}$/.test(sourceCurrency) ||
    typeof amount !== "string" ||
    !/^\d{1,12}(?:\.\d{1,4})?$/.test(amount) ||
    !/[1-9]/.test(amount) ||
    !Number.isInteger(travelers) ||
    (travelers as number) < 1 ||
    (travelers as number) > 20 ||
    !Number.isInteger(durationDays) ||
    (durationDays as number) < 1 ||
    (durationDays as number) > 365 ||
    (startDate !== "" && !isoDay(startDate)) ||
    typeof updatedAt !== "string" ||
    !Number.isFinite(Date.parse(updatedAt))
  ) {
    return null;
  }

  return {
    id,
    title,
    destination,
    sourceCurrency,
    amount,
    travelers: travelers as number,
    durationDays: durationDays as number,
    startDate: startDate as string,
    updatedAt,
  };
}

export function readTripDrafts(storage: DraftStorage | null): DraftRead {
  if (!storage) return { status: "unavailable", drafts: [] };
  let source: string | null;
  try {
    source = storage.getItem(TRIP_DRAFT_KEY);
  } catch {
    return { status: "unavailable", drafts: [] };
  }
  if (source === null) return { status: "ok", drafts: [] };
  if (source.length > MAX_SERIALIZED_BYTES) return { status: "invalid", drafts: [] };
  try {
    const value: unknown = JSON.parse(source);
    if (
      !record(value) ||
      value.version !== VERSION ||
      !Array.isArray(value.drafts) ||
      value.drafts.length > MAX_DRAFTS
    ) {
      return { status: "invalid", drafts: [] };
    }
    const items = value.drafts.map(normalizeTripDraft);
    if (items.some((item) => item === null)) return { status: "invalid", drafts: [] };
    const drafts = items as TripDraft[];
    if (new Set(drafts.map((item) => item.id)).size !== drafts.length)
      return { status: "invalid", drafts: [] };
    return { status: "ok", drafts };
  } catch {
    return { status: "invalid", drafts: [] };
  }
}

export function saveTripDrafts(storage: DraftStorage | null, drafts: TripDraft[]): boolean {
  if (!storage || drafts.length > MAX_DRAFTS || drafts.some((item) => !normalizeTripDraft(item)))
    return false;
  if (new Set(drafts.map((item) => item.id)).size !== drafts.length) return false;
  const envelope: DraftEnvelope = { version: VERSION, drafts };
  const payload = JSON.stringify(envelope);
  if (payload.length > MAX_SERIALIZED_BYTES) return false;
  try {
    storage.setItem(TRIP_DRAFT_KEY, payload);
    return true;
  } catch {
    return false;
  }
}

export function upsertTripDraft(drafts: TripDraft[], item: TripDraft): TripDraft[] | null {
  const normalized = normalizeTripDraft(item);
  if (!normalized) return null;
  const next = [normalized, ...drafts.filter((draft) => draft.id !== item.id)];
  return next.length <= MAX_DRAFTS ? next : null;
}

export function clearTripDrafts(storage: DraftStorage | null): boolean {
  if (!storage) return false;
  try {
    storage.removeItem(TRIP_DRAFT_KEY);
    return true;
  } catch {
    return false;
  }
}
