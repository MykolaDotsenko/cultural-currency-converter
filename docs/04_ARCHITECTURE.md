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

A successful conversion can be serialized into a short-lived signed **trusted conversion snapshot** for downstream progressive features. Consumers must derive financial inputs from that server-signed snapshot rather than trusting hidden/form-posted copies of the rate or result. Runtime AI explanation and Real Payment Estimate share this neutral exchange-layer boundary; neither owns or recalculates the original FX truth.

Real Payment Estimate is deterministic financial scenario arithmetic over explicit assumptions. It may model user-entered FX markup and fixed fees, but it must not infer bank/card/ATM/DCC/merchant fees. A failure in this optional surface must not invalidate the already successful conversion.

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
