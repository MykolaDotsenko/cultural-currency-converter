# Architecture

## Current shape

Cultural Currency Converter is a Django modular monolith with server-rendered web UI.

```text
Django view / form
        ↓
application use case / query
        ↓
domain rules
        ↓
ORM / cache / provider adapter
```

This layering is a practical ownership guide, not a requirement to create a class for every step.

## Web

Current web ownership:

- Django templates render the page and HTMX fragments;
- HTMX handles server-driven partial updates;
- TypeScript adds focused behaviour such as pickers, persistence helpers and chart loading;
- Vite builds frontend assets;
- Tailwind/project CSS provide the visual system;
- project-owned CSP middleware constrains executable/browser content on public responses, with an explicit report-only/enforce rollout mode and a separate Django-admin compatibility policy.

Avoid turning the web product into a client SPA unless a future requirement demonstrates a clear benefit.

## Django apps

### common

Cross-cutting web/runtime utilities such as health, middleware, observability, Vite integration and shared presentation helpers.

### accounts

Authentication, account preferences and account lifecycle.

### countries

Country/currency identity, temporal relationships and imported reference metadata.

### exchange

Current/historical FX, forms, application workflow, provider normalization, caching and rate-series presentation.

### culture

Curated destination context, typical prices, cultural facts/stories and provenance.

### media

Managed media metadata, validation, ingestion/publication and runtime media selection.

### travel

Saved pairs and recent conversion state/persistence.

These boundaries can change if responsibilities materially change. Prefer moving ownership over creating a duplicate “service” layer.

## Domain and application code

Use pure domain code where a rule can be expressed independently of Django/request state.

Use an application function/service when work coordinates multiple boundaries such as:

- validating a conversion request;
- reading reference data;
- calling a provider/cache;
- composing result/context;
- persisting user-owned state.

Views should remain focused on HTTP concerns and presentation orchestration.

## Money Context Engine

`apps/exchange/money_context.py` is the shared application contract for composing trusted conversion meaning with optional destination context.

The contract keeps these concerns explicit:

- the `ConversionResult` remains the authoritative financial result;
- current destination context may add sourced local-value and payment guidance;
- historical conversions and currency-only conversions do not silently receive current destination meaning;
- optional destination enrichment has explicit `available`, `empty`, `not_applicable` and `degraded` states;
- known database/data/decimal enrichment failures fail open without replacing the conversion;
- unexpected programming errors still propagate;
- destination country, optional canonical city scope, context date and price currency must remain consistent with the conversion contract.

The Money Context Engine is not a second datastore, rate provider or calculation truth source. It is an application-level composition boundary intended for reuse by budget, destination comparison, saved-trip, camera and mobile/offline flows. Canonical city scope now travels through this contract so those consumers do not need a parallel city-context path.

Destination mode is deliberately an entry adapter, not a second conversion engine. It resolves an explicit current country/city selection to the current primary destination currency, then redirects to the canonical converter with normalized destination scope. It performs no FX-provider call itself; conversion truth, source/effective-date semantics and context composition remain centralized.

`apps/exchange/budget.py` is the first pure-domain consumer of that contract. It compares an explicitly selected destination amount basis with a user/editorial daily basket built from already-sourced `TypicalPriceContext` values. It does not query providers, infer missing categories or establish a universal cost-of-living truth. Country-level interpretation excludes city-only observations; city-level interpretation may use the selected city plus visibly national fallback rows already present in the MoneyContext.

### Budget interpretation web trust boundary

The budget web flow does not trust editable browser fields for financial truth.

A short-lived signed budget-context token carries:

- the already-signed conversion snapshot;
- original FX fetch/policy metadata needed to reconstruct the trusted conversion contract;
- destination country and optional canonical city scope;
- the local-context as-of date.

On submit, the endpoint reconstructs the trusted conversion, rebuilds current sourced destination context for that signed scope/date, and applies only the user-visible budget assumptions. Posted fields cannot replace the conversion amount, rate, destination scope or source provenance.

The token does not serialize price rows as truth. Price anchors are reloaded from the project-owned reviewed data layer so retired/unpublished or invalid context is not kept alive merely because an old browser form still exists.

### Saved trip budget continuity

Trip Budget Remaining is a persistence/domain consumer, not a second financial engine.

- `SavedScenarioObservation(kind=initial)` fixes the original destination-currency reference budget.
- `SavedScenarioSpendEntry` stores only an explicitly confirmed destination-currency amount, confirmation source and timestamp.
- spend entries are immutable after creation; correction is delete-and-add;
- web spend submissions carry a persisted idempotency key so replaying the same confirmation cannot double-count the budget;
- add/remove operations serialize through the parent scenario transaction boundary;
- scenario creation writes one `initial` observation, and the database prevents any second `initial` observation for that scenario, keeping the remaining-budget baseline structurally unique;
- scenario-level service validation enforces destination-currency minor units even when a future caller does not use the web form;
- later FX re-check observations never rewrite the remaining-budget baseline;
- `apps/travel/trip_budget.py` performs deterministic remaining/over-reference/per-day arithmetic without provider access.

Receipt images, merchants and free-text purchase descriptions are deliberately outside this persistence contract. The camera foundation now provides an ephemeral extraction/review adapter, but it does **not** persist spend in this slice. A later adapter may feed a confirmed amount into the same service only after the extraction has been shown to and confirmed by the user.

### Camera extraction trust boundary

Camera mode is an optional adapter around the canonical converter, not a second financial engine.

- accepted uploads are bounded JPEG/PNG/WebP rasters and are decoded through the existing safe-image validator before provider access;
- raw bytes are read for the single extraction request and are not written to application database or managed-media storage;
- model output is schema-constrained and normalized into one project-owned amount/currency candidate or an explicit ambiguous/no-price state;
- ambiguous/no-price/provider-failure results fail closed without conversion;
- a short-lived signed token proves that a reviewed candidate originated from the extraction flow, while the user may explicitly correct amount/currency before proceeding;
- corrected/confirmed values still pass the canonical amount/minor-unit validation and canonical converter;
- camera extraction never supplies FX rates, fees, merchant/account identity or hidden banking data.

The current provider is feature-flagged Gemini multimodal extraction. CI uses fake providers; live provider calls are not required for tests.

## Persistence

PostgreSQL is the production-oriented durable store. Local development can use SQLite.

Use database constraints for durable invariants such as uniqueness/ownership where appropriate.

Keep transactions short. External network calls should not be intentionally performed while holding database row locks or a transaction that does not need to remain open.

Database recovery is based on native PostgreSQL logical archives. Recovery targets a fresh empty database, validates archive integrity before restore, restores atomically in one transaction and verifies the recovered schema/data before application cutover. The recovery path deliberately does not make destructive in-place restore the default.

PostgreSQL recovery does not imply that managed media/object bytes are backed up; deployment storage must provide its own durability/versioning/backup contract.

Managed media storage is environment-aware. Local/test/demo/preview may use Django filesystem storage, but production configuration must select the S3-compatible object-storage backend. The storage config requires a separate public HTTPS media origin; that validated origin is the only external image source added to CSP. Content-addressed managed filenames are served with long-lived immutable cache metadata. Provider credentials remain outside application configuration through the normal S3/IAM credential chain.

Object storage makes media bytes durable across application deploys, but durability is not the same as backup. Bucket versioning/retention and restore evidence remain deployment responsibilities.

## Caching

Caching is an optimization, coordination and resilience mechanism, not a second semantic truth source.

Local/test execution defaults to Django's process-local memory cache. Preview and production require a shared Redis-compatible cache through `CACHE_URL` so FX cache entries and short-lived AI cooldown/lock state are coherent across application instances.

Cache keys should include the identity needed to distinguish financial meaning: pair, date/mode and other relevant provider semantics. Deployment namespaces are separated with environment-specific key prefixes.

Validate cached objects before reuse when corrupted or semantically mismatched data could produce a wrong financial result. A cache outage must not make a cached value authoritative or change financial correctness: FX gateways may bypass the cache and AI coordination fails open to bounded live generation/deterministic fallback.

## External providers

Provider-specific JSON stays behind adapters/normalizers.

The application/domain should consume stable project-owned values rather than spread provider field names through views and models.

See [Integrations, AI and media](INTEGRATIONS_AI_MEDIA.md).

## Financial boundary

Use `Decimal` for money/rate arithmetic and keep source/effective-date semantics explicit.

Same-currency conversion can bypass unnecessary provider work while preserving clear result semantics.

## AI boundary

AI is optional enrichment. It receives bounded trusted packets and does not establish FX rates, historical observations or published factual truth.

The currently configured runtime provider/model is an implementation choice and may be changed after evaluation without redesigning the financial domain.

## Media boundary

Runtime pages select already available local/managed media. Searching or generating media should not become a normal conversion-request dependency.

## Observability

Structured logs and request identifiers make failures diagnosable without logging secrets or unnecessary personal data.

Health semantics are intentionally separated:

- liveness proves that the Django process can answer without touching dependencies;
- readiness treats PostgreSQL as a hard serving dependency;
- shared-cache failure is reported as degraded readiness rather than removing the instance from service because cache use is fail-open by design;
- FX and AI providers are never probed from health endpoints, so a third-party incident cannot create health-check traffic or make the whole application unready.

Provider/cache telemetry uses a small allowlist of operational fields such as provider, operation, outcome, attempt count, latency, cache status and AI token counts. Do not log provider URLs/query strings, raw payloads, conversion inputs or AI packet hashes merely for correlation.

## Architecture change guidance

Prefer the simplest architecture that protects the current product.

Before adding infrastructure or abstraction, ask:

- Which real problem does it solve?
- What duplication or risk does it remove?
- Can a plain function, Django feature or existing boundary solve it?
- What is the failure/operational cost?

Architecture may evolve. Update this document and the ADR log when a change creates a new durable project-wide convention.
