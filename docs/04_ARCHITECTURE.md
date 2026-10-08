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

`apps/culture/price_quality.py` is the reusable policy layer for current `TypicalPrice` data quality. It owns the shared freshness window, canonical category→unit mapping, normalized duplicate identity and stable issue codes without querying a parallel city-money store. ORM/model validation supplies the current primary-currency and canonical-city facts to that pure evaluator; database constraints enforce the subset of invariants that can be represented relationally. Runtime destination context remains fail-closed and continues to consume only the existing `TypicalPrice` rows that satisfy its publication/provenance/freshness gates.

`apps/culture/city_health.py` is a read-only maintenance/reporting consumer of that same quality contract. It batches active canonical cities, current primary currencies and published `TypicalPrice` rows, then classifies fresh city coverage, stale city data, fresh national fallback and provenance gaps without creating another datastore or web-facing ranking. Its 0–100 coverage score is deliberately operational: the four core categories (`coffee`, `casual_meal`, `transit`, `groceries`) contribute 25 points each for fresh city evidence or 15 points when only fresh national fallback exists. Stale and provenance-invalid data contribute zero points.

## Web

Current web ownership:

- Django templates render the page and HTMX fragments;
- HTMX handles server-driven partial updates;
- TypeScript adds focused behaviour such as pickers, persistence helpers and chart loading;
- the small core entry keeps HTMX coordination, typography and race-sensitive AI lifecycle handling, while converter/picker, consolidated Saved-state and rate-chart behaviour are demand-loaded only when matching DOM contracts exist;
- enhancement discovery reruns after HTMX swaps so lazy modules do not depend on initial `DOMContentLoaded` timing;
- Vite builds frontend assets and the browser-quality suite certifies route isolation so low-interaction pages do not eagerly pull unrelated dynamic chunks;
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

Shareable conversion rendering is a downstream snapshot boundary, not another conversion path. `apps/exchange/share_snapshot.py` signs the complete already-computed ConversionResult facts needed to render a share; `apps/exchange/web/share.py` validates that snapshot and performs no FX/account lookup. The public-by-link HTML/SVG surfaces are read-only, private/no-store and noindex; they retain effective/requested-date, fetched-at, provider, granularity and stale semantics. Share tokens intentionally outlive short runtime-AI tokens because the represented number is immutable rather than refreshed on open; rotating Django signing keys invalidates old links naturally.

Saved-scenario sharing is a separate privacy-minimized downstream boundary. `apps/travel/share_snapshot.py` accepts only an owner-visible `SavedScenario` and one already-persisted `SavedScenarioObservation`, verifies the observation belongs to that scenario and signs a reduced public projection. The projection contains no user/account ID, scenario ID, private title, trip dates, duration/travellers, spend entries, Camera state or notification state. `apps/travel/share_web.py` renders only that signed projection and never loads the scenario, account or FX provider when a public link opens. Re-checking the private scenario later does not mutate an existing public token; creating a new share is the only way to expose a newer stored observation.

`apps/exchange/result_summary.py` is a deterministic presentation-domain consumer of `ConversionResult` plus optional `MoneyContext`. It never calls a provider or AI model. Its priority order is trust-first: historical semantics, exact same-currency identity and labelled cached-reference state outrank optional enrichment. Only current non-stale results may use a reviewed `TypicalPriceContext` or reviewed payment context that has already passed Money Context provenance/freshness gates. Unsupported/zero purchase-equivalent states are ignored and the builder falls back to a neutral reference-rate limitation rather than failing the conversion or inventing affordability.

Destination mode is deliberately an entry adapter, not a second conversion engine. It resolves an explicit current country/city selection to the current primary destination currency, then redirects to the canonical converter with normalized destination scope. It performs no FX-provider call itself; conversion truth, source/effective-date semantics and context composition remain centralized.

`apps/culture/explore.py` is a provider-free discovery query over that same reviewed context layer. It first identifies published/fresh candidate country and canonical-city scopes, then reuses `build_destination_context()` as the final provenance/freshness gate. A city is publishable in Explore only when explicit canonical city price evidence survives that gate; national fallback cannot create a city card by itself. The GET query exposes no live rate, affordability score or ranking. Its presentation layer composes five provenance-bearing collections plus canonical region → country → city navigation, and hands exact scope into Converter, City Money Profile, one-sided Destination Comparison and My Places without creating a second geography or price model. Signed-in My Places writes through the owner-scoped travel persistence service; anonymous My Places stays browser-local.

Explore contextual AI is a separate explicit POST boundary, not part of the provider-free GET query. The POST accepts only a currently reviewed canonical destination plus a server-approved intent, rebuilds trusted DestinationContext server-side and forwards a bounded structured fact packet through the existing validated AI explanation stack. Raw prompts and arbitrary destination facts do not become application truth.

Explanation personalization is account-owned presentation metadata. Preferred language, answer-detail level and bounded travel emphasis may change only the locale/focus instruction carried by the server-built explanation packet. They never change the deterministic result or the packet's grounded fact/number/date/currency allow-lists; anonymous users and preference-read failures use safe defaults.

Budget and Destination Comparison contextual AI use an even tighter post-result boundary. After the deterministic domain result exists, the server builds one bounded `ExplanationPacket` per approved question and signs the complete packet together with its capability. The browser submits only that short-lived signed packet: intent, currencies, numbers, dates, destination scopes, basket totals and coverage are therefore application-owned and tamper-evident. The explanation endpoint does not call the FX gateway or recompute the deterministic result. Capability isolation prevents a Budget packet from being replayed as a Comparison request (and vice versa), while the shared structured-output validator rejects unknown facts/numbers/dates/currency codes plus positive destination-ranking or affordability claims. Model/cache failure returns a deterministic explanation without changing the financial result.

`apps/exchange/budget.py` is the first pure-domain consumer of that contract. It compares an explicitly selected destination amount basis with a user/editorial daily basket built from already-sourced `TypicalPriceContext` values. It does not query providers, infer missing categories or establish a universal cost-of-living truth. Country-level interpretation excludes city-only observations; city-level interpretation may use the selected city plus visibly national fallback rows already present in the MoneyContext.

`apps/exchange/comparison.py` composes two current MoneyContext values only when they share the same source amount/currency and use different destination scopes. It applies one shared reference-budget assumption set to both sides, preserves each destination's full ConversionResult, MoneyContext availability state, local currency/scope/provenance and intentionally exposes no winner/ranking primitive. The shipped web adapter obtains both trusted conversions through the canonical converter application path using one shared current-rate gateway, then passes the two MoneyContext values into this domain contract. It does not create an independent comparison-rate calculation path; GET remains provider-free and provider failure on either side prevents a misleading partial financial comparison.

The Same Amount Across Destinations surface is a separate orchestration over canonical current conversions and MoneyContext, not a new rate or cost-of-living engine. It evaluates two to four explicit destination scopes independently, preserves submitted order and each destination's provider/effective-date/stale/provenance meaning, and may surface partial success without synthesizing a winner, PPP claim or affordability rank.

### Budget interpretation web trust boundary

The budget web flow does not trust editable browser fields for financial truth.

A short-lived signed budget-context token carries:

- the already-signed conversion snapshot;
- original FX fetch/policy metadata needed to reconstruct the trusted conversion contract;
- destination country and optional canonical city scope;
- the local-context as-of date.

On submit, the endpoint reconstructs the trusted conversion, rebuilds current sourced destination context for that signed scope/date, and applies only the user-visible budget assumptions. Posted fields cannot replace the conversion amount, rate, destination scope or source provenance.

The token does not serialize price rows as truth. Price anchors are reloaded from the project-owned reviewed data layer so retired/unpublished or invalid context is not kept alive merely because an old browser form still exists.

### Camera extraction trust boundary

Camera extraction is a separate sensitive-input boundary and does not bypass Money Context or Trip Budget rules.

- the browser uploads media only after explicit user action;
- `CameraUploadForm` performs early file-size/type checks, while `sanitize_camera_image` remains the authoritative decode/normalization boundary;
- accepted images are decoded in memory, bounded by bytes/pixels/dimensions, EXIF orientation is applied, metadata is discarded and the result is re-encoded as a normalized JPEG;
- only the sanitized in-memory bytes may cross the configured multimodal provider boundary;
- the project-owned provider schema requests amount, currency, semantic kind and confidence only;
- raw media, merchant identity, receipt text and banking identifiers are not persisted;
- provider output is normalized into `CameraAmountCandidate` values and remains untrusted until the user confirms or corrects it;
- signed camera candidate/confirmation tokens are short-lived and scope-bound to the saved scenario;
- live provider calls are forbidden inside database transactions;
- confirmation itself never writes spend;
- a separate explicit POST consumes the short-lived scenario-scoped confirmed token and routes it through the existing idempotent `SavedScenarioSpendEntry` service with source=`camera`;
- the signed token is the sole amount/currency source for that handoff; an editable browser amount cannot override it;
- the confirmed token carries a signed unique confirmation id that becomes the spend idempotency key, so replaying the same handoff cannot double-count the trip budget while another explicit confirmation remains independent.

This keeps OCR/model uncertainty upstream of deterministic financial persistence and keeps Camera persistence inside the same spend contract as manual confirmation.

### Offline destination pack boundary

`apps/travel/offline_pack.py` defines the first versioned offline snapshot contract for saved budget scenarios.

The offline pack is generated on demand and is not another live financial engine:

- it never calls an FX provider;
- the newest already-stored scenario observation is exported as a **stored reference** with provider/effective-date/fetch/stale semantics;
- Trip Budget Remaining is still calculated from the immutable initial scenario observation, so a later FX re-check cannot move the spending baseline;
- reviewed destination prices/payment guidance are re-read from the canonical provenance-aware data layer at download time;
- destination-context failure degrades locally and does not remove the saved FX/budget sections;
- the HTML export is self-contained, script-free and has no remote stylesheet/image dependency;
- the pack carries an explicit format version, generation time and context as-of date;
- opening the file offline performs no refresh and must never make the stored FX observation look live;
- the server does not persist a second copy of the generated pack.

The portable HTML pack remains the most durable cross-browser/off-app export. The installed PWA now reuses this same snapshot meaning through a separate explicit device-copy contract rather than caching arbitrary live pages.

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
- saved-scenario detail does not query current destination context by default; an explicit `?local_context=1` request calls the canonical provider-free `build_destination_context()` contract using the latest already-stored observation output only as a purchase-equivalent amount anchor;
- the local-context refresh writes no scenario data and has explicit available/empty/degraded presentation states, so reviewed prices/payment guidance cannot rewrite immutable FX observations or the Trip Budget Remaining baseline.

Receipt images, merchants and free-text purchase descriptions are deliberately outside this persistence contract. A future camera adapter may feed a confirmed amount into the same service only after the extraction has been shown to and confirmed by the user.

## Persistence

PostgreSQL is the production-oriented durable store. Local development can use SQLite.

Use database constraints for durable invariants such as uniqueness/ownership where appropriate.

Keep transactions short. External network calls should not be intentionally performed while holding database row locks or a transaction that does not need to remain open.

Database recovery is based on native PostgreSQL logical archives. Recovery targets a fresh empty database, validates archive integrity before restore, restores atomically in one transaction and verifies the recovered schema/data before application cutover. The recovery path deliberately does not make destructive in-place restore the default.

PostgreSQL recovery does not imply that managed media/object bytes are backed up; deployment storage must provide its own durability/versioning/backup contract.

Managed media storage is environment-aware. Local/test/demo/preview may use Django filesystem storage, but production configuration must select the S3-compatible object-storage backend. The storage config requires a separate public HTTPS media origin; that validated origin is the only external image source added to CSP. Content-addressed managed filenames are served with long-lived immutable cache metadata. Provider credentials remain outside application configuration through the normal S3/IAM credential chain.

Object storage makes media bytes durable across application deploys, but durability is not the same as backup. Bucket versioning/retention and restore evidence remain deployment responsibilities.

## PWA / browser offline boundary

The root-scoped service worker is an availability shell, not a second application datastore. Navigation requests are always network-first; ordinary private/account/scenario HTML is never inserted into Cache Storage merely because it was viewed. If navigation fails, the worker returns either one explicitly saved private trip snapshot for that exact saved-scenario route or the generic public offline shell.

Only public same-origin build/PWA assets use automatic runtime caching. Private trip snapshots use a separate cache namespace and can be written only by the saved-scenario UI after the authenticated user chooses **Save trip for offline**. The service worker has no code path that writes private snapshots itself. Each snapshot is rendered from the canonical `OfflineDestinationPack` contract, carries `private, no-store` HTTP semantics on the server, contains no executable script and stores its version/revision/generation timestamp in explicit browser metadata.

`apps/travel/offline_snapshot.py` derives a deterministic revision from the saved scenario, budget items, immutable FX observations and confirmed spend. Online scenario detail compares that revision with device metadata: a changed spend/re-check/planning state marks the offline copy out of date and changes the explicit action to **Refresh offline copy**. A time-based 24-hour reminder is additional conservative lifecycle guidance, not a claim that reviewed context or FX became invalid at exactly that threshold. Offline rendering always says stored/offline snapshot, never live/current.

The private cache is local to the browser/device, capped by UI metadata and removable explicitly. Returning to anonymous state clears the private cache and metadata on the next online page load. Service-worker registration and all snapshot controls remain progressive enhancement: failure must not affect conversion, saved state, the portable HTML pack, accessibility or no-JavaScript behavior.

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


## Durable personalization boundary

`apps/travel/personalization.py` owns durable My Places and SavedComparison persistence. The browser never sends a trusted currency/rate/result for My Places: it sends only canonical country/city identity, and account re-entry resolves current currency from `CountryCurrency`. Browser-local place migration is explicit; sign-in alone does not invoke it.

Destination Comparison remains the only comparison calculation path. A successful comparison may issue a short-lived signed canonical-input token. `SavedComparison` stores those inputs and normalized basket assumptions only. GET reopen is provider-free; explicit Re-check posts the saved fields back to the canonical comparison endpoint, preserving route isolation and preventing a second comparison engine.


### Product identity boundary

Open Food Facts product data is optional descriptive context. `integrations/product_data/open_food_facts.py` owns HTTP/schema normalization; `apps/exchange/product_context.py` owns cache, local upstream budget, signed carry-forward token and trusted provenance validation. The Shopping form/domain never receives a product price from this integration.

A barcode lookup is an explicit user action. Product identity can disappear without changing Shopping inputs or FX output. A signed context token prevents repeat network lookups between identity discovery and calculation, while tampered/expired identity is simply omitted rather than rejecting the financial calculation.

### Public API v1 boundary

`apps/exchange/api_v1.py` is a transport adapter, not a parallel application layer. The public v1 conversion endpoint validates with `CurrentConversionForm`, builds the same `ConverterSubmissionCommand` meaning and calls `run_converter_submission` with the canonical gateway factories. It serializes `ConversionResult` and `MoneyContext` without recalculation.

API invariants:

- decimal financial values cross JSON as strings;
- historical requested/effective-date and observation-granularity meaning is preserved;
- provider attribution and stale state are never dropped;
- current destination enrichment remains optional/fail-open exactly as in Money Context;
- historical conversion cannot acquire current destination context;
- public v1 is read-only and account-free;
- future authenticated write/sync APIs require a separate credential/scope/revocation decision rather than reusing browser session assumptions.

Reference metadata is provider-free and short-cacheable. Conversion output is `private, no-store`. Native clients may store returned snapshots only if they retain freshness/provenance state and do not relabel them as current.

