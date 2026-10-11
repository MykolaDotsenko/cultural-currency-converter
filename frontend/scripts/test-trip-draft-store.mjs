import assert from "node:assert/strict";
import { test } from "node:test";

import {
  clearTripDrafts,
  normalizeTripDraft,
  readTripDrafts,
  saveTripDrafts,
  TRIP_DRAFT_KEY,
  upsertTripDraft,
} from "../src/behaviors/trip-draft-store.ts";

const draft = Object.freeze({
  id: "c3793d17-a928-4618-bbe7-dc684ab102d4",
  title: "Tokyo journey",
  destination: "JP:tokyo",
  sourceCurrency: "EUR",
  amount: "300.50",
  travelers: 2,
  durationDays: 10,
  startDate: "2026-12-01",
  updatedAt: "2026-10-11T10:00:00.000Z",
});

function storage() {
  const values = new Map();
  return {
    values,
    getItem(key) {
      return values.get(key) ?? null;
    },
    setItem(key, value) {
      values.set(key, value);
    },
    removeItem(key) {
      values.delete(key);
    },
  };
}

test("no reads write or upload drafts automatically", () => {
  const local = storage();
  assert.deepEqual(readTripDrafts(local), { status: "ok", drafts: [] });
  assert.equal(local.values.size, 0);
});

test("explicitly saved valid draft is returned without FX or personal account state", () => {
  const local = storage();
  assert.equal(saveTripDrafts(local, [draft]), true);
  const result = readTripDrafts(local);
  assert.equal(result.status, "ok");
  assert.deepEqual(result.drafts, [draft]);
  const raw = local.getItem(TRIP_DRAFT_KEY);
  assert.ok(raw);
  for (const forbidden of ["rate", "outputAmount", "userId", "password", "receipt"]) {
    assert.equal(raw.includes(forbidden), false);
  }
});

test("upsert edits without creating a duplicate; remove requires explicit save", () => {
  const local = storage();
  assert.equal(saveTripDrafts(local, [draft]), true);
  const updated = { ...draft, amount: "500.00" };
  const next = upsertTripDraft(readTripDrafts(local).drafts, updated);
  assert.ok(next);
  assert.equal(next.length, 1);
  assert.equal(readTripDrafts(local).drafts[0].amount, "300.50");
  assert.equal(saveTripDrafts(local, next), true);
  assert.equal(readTripDrafts(local).drafts[0].amount, "500.00");
});

test("malformed, oversized and future storage versions fail closed without deletion", () => {
  const local = storage();
  for (const invalid of [
    "{broken",
    JSON.stringify({ version: 2, drafts: [draft] }),
    JSON.stringify({ version: 1, drafts: [{ ...draft, amount: "NaN" }] }),
    "x".repeat(20_000),
  ]) {
    local.setItem(TRIP_DRAFT_KEY, invalid);
    assert.deepEqual(readTripDrafts(local), { status: "invalid", drafts: [] });
    assert.equal(local.getItem(TRIP_DRAFT_KEY), invalid);
  }
});

test("reject corrupted date, fractional users, unsupported destination syntax and XSS-like names", () => {
  const fields = [
    { startDate: "2026-02-30" },
    { travelers: 1.5 },
    { destination: "JP/<img>" },
    { title: "bad\nname" },
    { amount: "0.0000" },
    { sourceCurrency: "EURO" },
  ];
  for (const field of fields) assert.equal(normalizeTripDraft({ ...draft, ...field }), null);
});

test("hard cap of eight drafts and IDs are enforced", () => {
  const local = storage();
  const entries = Array.from({ length: 8 }, (_, index) => ({
    ...draft,
    id: `a7${String(index).padStart(6, "0")}-a928-4618-bbe7-dc684ab102d4`,
  }));
  assert.equal(saveTripDrafts(local, entries), true);
  assert.equal(saveTripDrafts(local, [...entries, draft]), false);
  assert.equal(saveTripDrafts(local, [draft, draft]), false);
  assert.equal(upsertTripDraft(entries, draft), null);
});

test("blocked storage never crashes or loses the previously stored value", () => {
  const blocked = {
    getItem() {
      throw new Error("private mode");
    },
    setItem() {
      throw new Error("quota");
    },
    removeItem() {
      throw new Error("blocked");
    },
  };
  assert.deepEqual(readTripDrafts(blocked), { status: "unavailable", drafts: [] });
  assert.equal(saveTripDrafts(blocked, [draft]), false);
  assert.equal(clearTripDrafts(blocked), false);
});

test("clearing is explicit and local", () => {
  const local = storage();
  saveTripDrafts(local, [draft]);
  assert.equal(clearTripDrafts(local), true);
  assert.deepEqual(readTripDrafts(local), { status: "ok", drafts: [] });
});
