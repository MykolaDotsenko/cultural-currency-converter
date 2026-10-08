# Public API v1

The first public API slice is a **read-only adapter over existing application/domain truth**. It is intended for native/mobile and server-to-server consumers without creating a second currency-conversion implementation.

## Stability contract

Base path: `/api/v1/`

Every JSON response includes:

- `schemaVersion: "1"`;
- `X-API-Version: 1`;
- `X-Content-Type-Options: nosniff`.

Within v1, existing field meanings are stable. New optional fields may be added only when older clients can safely ignore them. Breaking field/semantic changes require a new major path such as `/api/v2/`.

Financial decimals are serialized as **JSON strings**, never binary JSON numbers. Dates use ISO `YYYY-MM-DD`; timestamps use timezone-aware ISO 8601.

## Endpoints

### `GET /api/v1/`

Capability discovery. This endpoint is provider-free.

The current v1 capabilities are:

- reference metadata;
- canonical latest conversion;
- canonical historical conversion;
- Money Context attached to a successful conversion.

Account mutation is explicitly reported as unavailable in this slice.

### `GET /api/v1/reference/`

Returns active currency metadata and current primary destination currency relationships, including active canonical cities.

This is reference metadata only. It performs no FX request and is cacheable for a short period.

### `POST /api/v1/conversions/`

Accepts `application/json` only. The body is bounded to 16 KiB and unknown fields fail closed.

Supported fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `amount` | decimal string | Required. Uses the same minor-unit/ambiguity validation as the web converter. |
| `sourceCurrency` | string | Required ISO-style currency code known to the canonical model. |
| `destinationCurrency` | string | Required ISO-style currency code known to the canonical model. |
| `sourceCountry` | string | Optional country context. Current mode validates the currency relationship. |
| `destinationCountry` | string | Optional country context. Current mode validates the currency relationship. |
| `destinationCitySlug` | string | Optional canonical city. Requires a valid selected destination country. |
| `rateMode` | `latest` or `historical` | Defaults to `latest`. |
| `requestedDate` | ISO date string | Required only for historical mode. |

The endpoint validates through `CurrentConversionForm` and executes through `run_converter_submission`. It therefore shares the same currency metadata, historical lifecycle rules, FX gateways, Decimal arithmetic, rounding, stale semantics and Money Context composition as the canonical web converter.

The success payload contains:

- immutable conversion facts: input/output, rate, currencies, requested/effective date, fetched time, historical granularity, provider attribution, stale state and exact-identity state;
- Money Context state and destination scope;
- reviewed price/payment context when available, with source/provenance and observation dates;
- optional official economic context (inflation and comparative price-level evidence) with explicit period, source dataset, benchmark, status and provenance. These fields are broad statistical context and are not merchant prices or purchasing-power claims;
- optional public-holiday calendar context containing national holidays in the bounded current destination window, with source provenance. It does not represent entity-specific opening hours.

Historical conversions return Money Context as `not_applicable`; the API does not present current local-price/payment context as historical truth.

## Error contract

Errors use:

```json
{
  "schemaVersion": "1",
  "error": {
    "code": "stable_machine_code",
    "message": "Safe human-readable message"
  }
}
```

Validation errors may add `fields`. Historical coverage errors may add bounded structured `details`.

Current stable codes include:

- `invalid_json`;
- `invalid_request`;
- `unknown_fields`;
- `unsupported_media_type`;
- `payload_too_large`;
- `validation_error`;
- `historical_out_of_coverage`;
- `historical_observation_unavailable`;
- `unsupported_pair`;
- `provider_invalid_payload`;
- `provider_unavailable`;
- `conversion_unavailable`.

Provider exception messages are never returned verbatim.

## Privacy and authentication boundary

v1 currently exposes only public read-only product data and stateless conversion execution.

It does **not** expose:

- account profile/preferences;
- saved currencies/pairs/places;
- saved scenarios or confirmed spend;
- Camera uploads/extractions;
- notifications;
- write/delete operations.

The conversion POST is CSRF-exempt because it is stateless and makes no account/data mutation. This is not permission for future write APIs to be CSRF-exempt or unauthenticated.

Native apps can call same-origin HTTPS endpoints without browser CORS. Cross-origin browser access is intentionally not enabled by this slice. Broad third-party browser exposure requires an explicit allow-list/rate-limit/abuse-control decision rather than a permissive wildcard.

## Caching and freshness

- capability/reference metadata: short public cache (`max-age=300`);
- conversion responses and errors: `private, no-store`.

A conversion response always carries its effective/fetched/provider/stale semantics. API clients must not relabel a stored response as a live current rate.

## Mobile rule

A native/mobile client must treat this API as a transport boundary, not as permission to reimplement financial logic locally.

The backend remains authoritative for:

- conversion calculation;
- historical date/coverage meaning;
- rounding and currency minor units;
- Money Context scope/provenance;
- stale/provider semantics.

Offline mobile storage may retain already-returned snapshots only when it preserves those timestamps/status fields and labels them stored/offline rather than current.
