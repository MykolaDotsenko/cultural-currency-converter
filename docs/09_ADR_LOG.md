# Decision Log

This file records durable decisions that help future developers understand *why* the current architecture looks the way it does.

A decision is not permanent. Each entry includes a reason to revisit it.

## ADR-001 — Django server-rendered web

**Status:** active

The web product currently uses Django templates with HTMX and focused TypeScript enhancements.

**Why:** the product is form/content heavy, benefits from server ownership and does not require SPA-wide client state.

**Revisit when:** a concrete user flow is materially simpler or better with a larger client application.

## ADR-002 — Modular monolith

**Status:** active

Business capabilities live in Django apps inside one deployable application.

**Why:** current scale does not justify distributed-system overhead.

**Revisit when:** independent scaling/deployment/ownership becomes a measured requirement.

## ADR-003 — Decimal and explicit financial semantics

**Status:** active

Money/rate calculations use Decimal semantics and preserve source/date meaning.

**Why:** binary floating point and implicit date semantics can produce misleading financial results.

**Revisit when:** only if an alternative preserves or improves correctness and explainability.

## ADR-004 — Country and currency are separate temporal concepts

**Status:** active

Country/currency relationships are modelled explicitly with time scope.

**Why:** currencies can be shared and can change over history.

**Revisit when:** domain requirements demonstrate a better equivalent model without losing temporal meaning.

## ADR-005 — External providers stay behind adapters

**Status:** active

Provider payloads are normalized before application/domain use.

**Why:** this limits vendor coupling and centralizes validation/failure semantics.

**Revisit when:** a provider becomes a durable first-party domain source whose schema is intentionally adopted.

## ADR-006 — PostgreSQL as production durable store

**Status:** active

Production-oriented persistence targets PostgreSQL; SQLite remains useful locally.

**Why:** PostgreSQL supports the constraints/concurrency behaviour expected for user-owned state.

**Revisit when:** deployment constraints or scale justify another durable store.

## ADR-007 — Progressive enhancement and accessibility

**Status:** active

Core web tasks are server-rendered and usable with minimal client behaviour; accessibility is considered in normal implementation/QA.

**Why:** resilience, simpler ownership and broader usability.

**Revisit when:** individual enhancements can improve UX without losing these properties.

## ADR-008 — AI is enrichment, not truth

**Status:** active

AI may synthesize trusted facts into bounded explanatory output. It does not establish FX rates, historical observations or published factual provenance.

**Why:** factual/financial correctness needs deterministic and attributable sources.

**Revisit when:** never based solely on model capability; only if the product can preserve equivalent trust/provenance guarantees.

## ADR-009 — Media authenticity over spectacle

**Status:** active

Use curated managed photography for premium destination imagery and authentic sourced archival media for historical evidence. Country hero/teaser surfaces do not fall back to cartoon or decorative illustrations; if suitable photography is unavailable, the layout remains image-free.

**Why:** weak or synthetic-looking imagery lowers trust and perceived product quality, while historical imagery can easily imply false authenticity.

**Revisit when:** a new visual medium can match the same premium, provenance and authenticity bar.

## ADR-010 — Current context is not automatically historical

**Status:** active

Historical conversion does not backdate current prices/payment customs.

**Why:** temporal truth matters more than filling a contextual card.

**Revisit when:** explicit historical context datasets exist.

## ADR-011 — Account recent history is opt-in

**Status:** active

Signing in does not silently upload browser-local recent history. Cross-device recording starts only after explicit opt-in.

**Why:** recent conversion history can reveal travel/financial context and deserves a clear privacy boundary.

**Revisit when:** only with an equally explicit consent/privacy model.

## ADR-012 — Future mobile technology is selected at implementation time

**Status:** active

React Native/Expo is a current candidate, not a permanently pinned roadmap commitment.

**Why:** mobile ecosystem versions and best practices change faster than the product roadmap.

**Product trigger:** mobile becomes active when point-of-use value is ready to reuse safely—specifically a stable external/mobile API, the Money Context Engine, and explicit offline/stale-rate semantics. Mobile is strategically important for in-trip use, but that does not justify prematurely replacing the server-rendered web architecture.

**Revisit when:** mobile work becomes active; benchmark the then-current stable options.

## ADR-013 — Shared cache for deployed coordination

**Status:** active

Preview and production use a shared Redis-compatible Django cache; local/test execution can remain process-local unless a Redis URL is explicitly supplied.

**Why:** FX freshness/stale entries and short-lived AI cooldown/duplicate-generation locks must have coherent meaning across multiple application instances. Redis is used as an optimization/coordination layer, not a financial truth source, so cache failures fail open to provider access or deterministic fallback instead of corrupting domain semantics.

**Revisit when:** measured scale, hosting constraints or reliability evidence justify a different shared cache with equivalent cross-instance atomic add/TTL behaviour and failure semantics.

## ADR-014 — CSP is enforced on the public web surface with an explicit rollout mode

**Status:** active

The public application uses a same-origin Content Security Policy that blocks inline/eval script execution, embedded objects and framing. Test runs enforce the policy. Preview and production must explicitly choose report-only or enforcement mode. Django admin receives a separate compatibility policy rather than weakening public pages.

**Why:** CSP is most valuable when it is an executable browser boundary, but deploying a strict policy without compatibility evidence can break HTMX/Vite or framework-owned admin templates. Separating the public and admin policies preserves a stronger default while keeping rollout observable and reversible.

Violation reporting is bounded and privacy-minimized: raw document URLs/query strings are not persisted or logged.

**Revisit when:** Django admin no longer needs inline compatibility, Trusted Types becomes practical for the current browser/runtime surface, or deployment telemetry justifies tightening/removing a directive.

## ADR-015 — Health checks distinguish serving dependencies from degradation

**Status:** active

Process liveness has no dependency probes. Readiness treats PostgreSQL as a hard dependency, while shared-cache failure reports a degraded-but-ready state. External FX and AI providers are never called by health endpoints; their availability is measured from bounded operational telemetry on real application requests.

**Why:** PostgreSQL unavailability prevents safe use of durable application state, but Redis and external providers already have explicit fail-open/fallback semantics. Turning every dependency incident into readiness failure would unnecessarily remove otherwise useful instances and could amplify provider incidents with synthetic probe traffic.

Operational logs use a stable field allowlist and avoid request/provider payloads and user conversion details.

**Revisit when:** a dependency becomes mandatory for every safe request, or the deployment platform requires a different health contract with equivalent semantics.

## ADR-016 — Database recovery restores into a fresh database

**Status:** active

PostgreSQL backups use native custom-format logical archives with a separate SHA-256 integrity record. Recovery verifies the archive, refuses a non-empty target and restores in a single transaction. Application cutover happens only after migration and data smoke checks against the recovered database.

**Why:** destructive in-place restore combines recovery with deletion and makes operator mistakes harder to contain. Restoring into a fresh database keeps the original database available for comparison/fallback, gives verification a clear boundary and makes failed restore attempts disposable.

The project does not infer production RPO/RTO from CI and does not treat database backup as media/object-storage backup.

**Revisit when:** the production platform provides a stronger tested point-in-time recovery mechanism or managed database workflow with equivalent integrity, verification and rollback properties.

## ADR-017 — Performance gates use deterministic growth budgets

**Status:** active

Production-build asset size, lazy-chunk boundaries, initial request count and selected ORM query counts are hard merge budgets derived from measured green-build baselines. Browser navigation timings remain evidence-only until the CI environment can produce sufficiently stable distributions.

**Why:** deterministic byte/query growth is highly actionable and repeatable, while strict wall-clock thresholds on shared CI runners create false failures. A budget should catch meaningful regressions without pretending that one lab run represents real-user performance.

The browser and non-browser frontend gates share one asset-budget definition so thresholds cannot drift between workflows.

**Revisit when:** real-user monitoring or a controlled performance runner provides stable Core Web Vitals/latency distributions suitable for regression thresholds.

## ADR-018 — Production managed media uses durable object storage

**Status:** active

Production managed-media bytes live in S3-compatible object storage rather than the application filesystem. Local, test, demo and preview execution may use filesystem storage when persistence across deploys is not part of the environment contract.

The application validates a public HTTPS media origin separately from the object-storage API endpoint. That origin is added only to the CSP image allowlist. Managed content-addressed objects use long-lived immutable browser caching; provider credentials stay in the standard S3/IAM credential chain rather than application metadata.

**Why:** the application database stores media provenance and object names, but a successful PostgreSQL restore cannot recover media bytes that disappeared from an ephemeral web-service filesystem. Object storage decouples managed media lifetime from application deploys and instances.

Durable object storage does not itself prove backup quality. Bucket versioning/retention and restore evidence remain deployment responsibilities and must not be inferred from CI.

**Revisit when:** the deployment platform provides an alternative durable media store with equivalent cross-deploy persistence, public delivery, provenance-compatible naming and tested restore properties.

## ADR-019 — Money Context Engine is a shared application contract

**Status:** active

Trusted conversion output and optional destination money context are composed through a project-owned Money Context application contract. The conversion remains the authoritative financial result; local-value/payment enrichment has explicit availability state and may degrade without invalidating conversion truth.

Historical and currency-only conversions do not silently receive current destination context. The contract also checks destination-country/date/price-currency consistency before exposing enrichment to downstream workflows.

**Why:** budget, destination comparison, saved trips, camera and mobile/offline use cases all need the same money meaning. A shared contract prevents each feature from inventing its own rate/local-value/payment semantics while preserving current fail-open and provenance boundaries.

**Revisit when:** a future domain boundary can provide the same semantics more cleanly without duplicating financial truth or coupling all consumers to web presentation structures.

## ADR-020 — Camera media is ephemeral and confirmation-gated

**Status:** active

User-selected Camera media is processed only after explicit action, normalized in memory and not persisted by the application. Before any external multimodal call, the image is decoded, size/pixel bounded, orientation-normalized, metadata-stripped and re-encoded. Provider output is restricted to a project-owned monetary candidate schema.

An extracted value is not financial truth. Explicit currency conflicts are blocked and the user must confirm or correct the amount before a short-lived scope-bound confirmation token is created. This token contains no source image, merchant text, receipt body or banking identifier. Camera extraction itself does not write `SavedScenarioSpendEntry`; persistence is a separate explicit **Add to trip budget** handoff through the existing idempotent spend service, using the token's signed confirmation id as the submission key.

**Why:** receipts, ATM screens and screenshots may contain sensitive information, while OCR/multimodal extraction is probabilistic. Ephemeral processing plus confirmation keeps sensitive media out of durable state and prevents model output from becoming silent financial input.

**Revisit when:** a proven on-device extraction path can provide equal or better accuracy with less external data transfer, or a user requirement justifies durable media storage with an explicit retention/deletion model.

## ADR-021 — Offline destination packs are explicit snapshots

**Status:** active

The first offline destination surface is a versioned, self-contained export generated from an account-owned saved budget scenario. It uses already-stored FX observations plus reviewed project-owned destination context and performs no live FX-provider call during export.

The downloaded pack labels FX as stored reference data with provider/effective-date/fetch/stale semantics, keeps Trip Budget Remaining anchored to the immutable initial observation, and records its own generation/context dates. The HTML representation contains no executable script or remote asset dependency and does not auto-refresh when reopened.

**Why:** offline utility is valuable only if stale/current meaning remains unambiguous. Caching an arbitrary live page or silently reusing an old rate would blur the project’s core financial trust boundary. A small explicit snapshot contract is portable to future PWA/mobile clients and can degrade destination enrichment without losing saved financial state.

The server does not persist generated pack files. A newly downloaded pack is the explicit refresh action.

**Revisit when:** native mobile or PWA work needs managed pack storage/background refresh. Any replacement must preserve explicit freshness, versioning, provenance and the separation between stored FX reference and live rates.

## ADR-022 — PWA cache is public-shell-only by default

**Status:** active

The web application may install a root-scoped service worker, but it does not cache arbitrary navigation HTML. Navigation remains network-only and falls back to a generic public offline shell when the network is unavailable. Cache Storage is limited to that shell plus public same-origin application/PWA static assets.

**Why:** account pages, saved scenarios, notifications and form responses can reveal travel/financial context. Automatically caching a page merely because the user viewed it would create a silent local persistence channel and could also make stored FX/context appear current offline. Installability is useful, but it must not erase the existing privacy and freshness boundaries.

The explicit Offline Destination Pack remains the canonical saved-trip snapshot meaning. The active-trip PWA view is now implemented as the required separate user-initiated/versioned contract rather than a broader navigation-cache rule.

**Revisit when:** a reviewed encrypted/user-controlled offline-state design can improve device-sharing protection while preserving ownership, deletion, freshness and stale/live semantics.

## ADR-023 — Private offline trips reuse the canonical pack and require explicit lifecycle controls

**Status:** active

PWA offline trip storage reuses the rendered OfflineDestinationPack. The browser stores it only after **Make available offline**, under a synthetic offline-trip URL in a dedicated private CacheStorage namespace. Ordinary Saved/account pages remain network-only. A deterministic opaque revision detects changes to saved scenario assumptions, stored FX observations or confirmed spend; reviewed context continues to use explicit generated/as-of dates rather than being folded into a misleading binary freshness token.

The browser removes one snapshot through **Remove offline copy** and performs best-effort removal before deleting its scenario. Normal sign-out and account deletion clear the private-trip cache namespace. Anonymous browser-local favourites/recent/My Places are intentionally not cleared by that operation.

**Why:** reusing one pack prevents a second offline financial calculation path. Explicit create/replace/remove semantics make sensitive device-local persistence visible, while keeping sign-out cleanup narrower than a broad browser-storage wipe.

**Revisit when:** device-bound encryption or another platform primitive can materially strengthen shared-device privacy without weakening offline availability or forcing silent background persistence.

## Adding/changing a decision

Create or update an ADR when a change affects a durable project-wide choice.

Do not use ADRs for routine refactors, one-off UI details or dependency patch versions.

When replacing a decision, explain:

- what changed;
- why the previous reasoning no longer wins;
- what new evidence/requirement justifies the change.
