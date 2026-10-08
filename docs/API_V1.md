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
- canonical foreign-shopping estimate;
- optional historical community unit-price observations;
- Money Context attached to a successful conversion.

Account mutation is explicitly reported as unavailable in this slice.

### `GET /api/v1/reference/`

Returns active currency metadata and current primary destination currency relationships, including active canonical cities.

This is reference metadata only. It performs no FX request and is cacheable for a short period.

### `GET /api/v1/products/{barcode}/`

Returns optional Open Food Facts product identity through the same bounded cache/throttle service used by Shopping. The response contains barcode, product name, brand labels, quantity, categories and source provenance/license. `price` is explicitly `null`: Open Food Facts is not a price source for this product.

Stable product lookup errors include `invalid_barcode`, `product_not_found`, `product_lookup_busy` and `product_source_unavailable`. Provider error details are not leaked. Responses are accepted only when the
provider's top-level and product-level barcodes, when present, match the requested
product under Open Food Facts' documented leading-zero normalization
(https://openfoodfacts.github.io/openfoodfacts-server/api/ref-barcode-normalization/).
The resolved HTTP origin must stay on world.openfoodfacts.org: a redirect to
another Open Facts database cannot silently inherit food-product attribution.
Any mismatch is an optional product-source error, never a price, fee or FX input.

The endpoint normalizes UPC/EAN barcode spellings before checking the shared
product cache and rejects malformed or all-zero codes with HTTP 400 before
accessing quota or upstream data. Every valid GET, including a cache hit,
consumes the same 60/minute per-peer API budget as conversions and Open Prices
observations. Quota exhaustion returns HTTP 429 `rate_limited` with
`Retry-After`; shared quota unavailability fails closed with HTTP 503
`quota_unavailable`. The separate upstream Open Food Facts limit continues to
report 429 `product_lookup_busy`. Neither case changes the trusted price/FX
boundary. Successful identity responses remain private-cacheable for one hour;
quota and validation errors are `private, no-store`.

### GET /api/v1/products/{barcode}/prices/

Opt-in, read-only **historical community price observations** for native/mobile
Shopping. Does not call the Open Food Facts product-identity source or any FX
provider. Returns up to five source-linked price observations from the existing
Open Prices cache/provider boundary. An empty observations array means only
that the bounded first provider page contained no eligible records; it does not
claim that a product has no prices anywhere.

The success envelope includes schemaVersion "1" and data:

- barcode: canonical Open Food Facts normalized product identity;
- evidenceType: historical_community_unit_price_observations;
- livePrice: null (never a current price or Shopping calculation input);
- source: Open Prices name, home URL and ODbL database license;
- sampling: bounded=true, providerPageSize=20, maxObservations=5,
  maxObservationAgeDays=365, representsMarketAverage=false;
- observations[]: productBarcode, **Decimal string** amount, currency,
  unit="UNIT", observedAt (ISO date), countryCode, locationLabel,
  discounted, proofId, recordUrl and retrievedAt (timezone-aware ISO timestamp).

Only exact matching barcodes, positive finite unit prices, dated non-duplicate
records with an explicit location and proof reference, and records within the
365-day window qualify. A proof ID is a reference, **not independently verified
proof contents**. These are community-submitted observations, not live offers,
a statistically representative market sample, a price history covering all
merchants or a price guaranteed at the user's store.

Every API request (including cached responses) shares the existing per-peer
60/minute API abuse-control gate with conversion/Shopping endpoints. A separate
shared Open Prices budget allows six upstream lookups/minute with 12-hour
positive and 1-hour empty provider caches. HTTP 429 price_lookup_busy means
provider budget exhaustion; 429 rate_limited means the caller API quota was
exceeded (includes Retry-After). HTTP 503 price_source_unavailable and
quota_unavailable fail closed without leaking source/cache details. Malformed,
all-zero or nonnumeric barcodes return HTTP 400 invalid_barcode before quota
or upstream work. All success and error responses are private, no-store.

No returned amount is ever used as itemPrice by
POST /api/v1/shopping/estimate/. The client must obtain an explicit
user-entered item price, shipping, fees and FX-markup assumptions separately.

### `POST /api/v1/shopping/estimate/`

Stateless foreign-shopping estimate for native/mobile clients. This uses the
**same** `ShoppingCalculationForm`, `quote_conversion`, and
`calculate_shopping_estimate` as the web Shopping page. It does not call
Open Food Facts, AI, duties/taxes providers, or a second financial engine.

All fields must be JSON strings, including monetary amounts:

| Field | Requirement | Meaning |
| --- | --- | --- |
| `purchaseCurrency` | required | Active purchase-currency code |
| `homeCurrency` | required | Distinct active home-currency code |
| `itemPrice` | required | Positive decimal string in purchase currency |
| `purchaseCountry` | optional | Current country/currency relationship is validated |
| `shipping` | optional | Purchase-currency decimal; defaults to zero |
| `knownFees` | optional | Purchase-currency decimal; defaults to zero |
| `fxMarkupPercent` | optional | Explicit percentage, defaults to zero; 0–25% |

The same currency minor-unit limits, bounds, and precision requirements as
the web form apply. Unknown fields fail closed; the body is capped at 16 KiB.
The response has `purchaseTotal`, `referenceHomeCost`,
`estimatedHomeCost`, `fxMarkupCost`, explicit `assumptions`, and
`unknownCosts`: duties, taxes, issuer or merchant fees that have **not** been
entered. All financial decimal fields are JSON strings. The nested
`conversion` reuses the v1 conversion serializer to expose unmodified
rate, provider keys, effective date, fetch timestamp, and stale state.
No checkout total, duty/tax guess, merchant rate, or affordability claim.

The shared conversion rate-limit quota applies after validation and before FX
work. Stable errors include `validation_error` (422),
`calculation_unavailable` (422), `provider_invalid_payload` (502),
`provider_unavailable` (503), `rate_limited` (429 with `Retry-After`),
and `quota_unavailable` (503). Responses are `private, no-store`.
This CSRF-exempt endpoint is stateless and never reads or mutates account data.

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
- `conversion_unavailable`;
- `calculation_unavailable` (Shopping estimate only);
- `rate_limited` (HTTP 429, with `Retry-After` in seconds);
- `quota_unavailable` (HTTP 503 if the shared abuse-control cache cannot enforce its budget).

Provider exception messages are never returned verbatim.

## Privacy and authentication boundary

v1 currently exposes only public read-only product data and stateless conversion/Shopping-estimate execution.

It does **not** expose:

- account profile/preferences;
- saved currencies/pairs/places;
- saved scenarios or confirmed spend;
- Camera uploads/extractions;
- notifications;
- write/delete operations.

Conversion and Shopping estimate POSTs are CSRF-exempt because they are stateless and make no account/data mutation. This is not permission for future write APIs to be CSRF-exempt or unauthenticated.

Native apps can call same-origin HTTPS endpoints without browser CORS. Cross-origin browser access is intentionally not enabled by this slice. Broad third-party browser exposure requires an explicit allow-list/rate-limit/abuse-control decision rather than a permissive wildcard.

## Abuse controls

Provider-backed current/historical conversions, Shopping estimates, product
identity lookups and community price observations share a fixed-minute quota of
**60 requests per minute per server-observed peer address**. It is checked
after input/barcode validation and before the canonical FX/application or
optional product-price providers (including cached GET responses);
same-currency exact conversions do not consume provider budget.
Exhaustion returns HTTP 429 with a whole-second Retry-After countdown. A
shared-cache outage fails closed as quota_unavailable instead of creating
unbounded provider traffic. Conversion errors and quota responses are not stored
by public caches.

By default, peer identity comes strictly from REMOTE_ADDR and caller-supplied
forwarding headers cannot affect the quota. Behind a shared reverse proxy, the
default may put multiple clients into one bucket.

Deployments can opt in with API_TRUSTED_PROXY_CIDRS, a comma-separated list of
exact IPv4/IPv6 proxy CIDRs (for example, 10.42.0.0/16). Only when the immediate
socket peer matches a configured trusted proxy will the quota use X-Forwarded-For;
it walks **right to left** through the trusted proxy chain and stops at the first
untrusted address, ignoring earlier user-spoofable entries. Malformed or oversized
headers use the peer quota. The selected address is HMAC-hashed before caching;
no raw client IP is stored in the quota key. Do not configure a whole-internet CIDR
or broadly trust local networks merely because HTTPS is proxy-terminated.

Before enabling the option, operators must confirm their proxy appends the real
connecting peer to X-Forwarded-For, ensure the application is reached only via
that verified trusted hop (or safely treats direct connections as direct peers),
and test a direct/spoofed request. This setting is intentionally separate from
DJANGO_HTTPS_MODE=proxy and SECURE_PROXY_SSL_HEADER. An ephemeral demo with a
process-local cache cannot guarantee cross-worker quotas; production/preview
requires a shared Redis cache. Native clients should honor Retry-After and
avoid background polling.

## Caching and freshness

- capability/reference metadata: short public cache (`max-age=300`);
- conversion/Shopping estimate responses and errors: `private, no-store`.

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
