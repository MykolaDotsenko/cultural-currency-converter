# Production 100/100 Execution Plan

This document defines the execution path for bringing the **current Cultural Currency Converter web product** from its present production-grade baseline to a strict internal **100/100 production-readiness score**.

It is an execution and release-readiness plan, not a replacement for the product roadmap. The roadmap describes what the product should become; this document describes the PR sequence, dependencies, acceptance gates and release evidence required to call the current web scope complete.

> The PR numbers below are the intended sequence from the current repository state. If GitHub numbering changes, preserve the order and scope rather than the literal number.

> Actual GitHub numbering has diverged from this original sequence. Treat the headings below as planned scope IDs, not as claims that GitHub PR #N implemented that exact scope. Current-production notes are authoritative where present.

## Current baseline

The plan was originally created from an earlier repository baseline. It is now synchronized through `master`:

`75cf9a7e337f1de15a4e80549cdee9b5621effc7`

The current product already includes:

- current and historical FX conversion with explicit provider/effective-date semantics;
- temporal country/currency modelling, historical ranges, chronological landmarks and Then & Now;
- smart current/historical country-currency filtering;
- explicit-assumption Real Payment Estimate;
- Money Context Engine composition with canonical city/national scope;
- Destination Mode, Destination Comparison and Same Amount Across Destinations;
- deterministic Budget Interpretation, SavedScenario persistence, explicit rate re-check, Trip Budget Remaining, Camera spend handoff and Offline Destination Pack;
- Returning-user Trip Home;
- provider-free Explore GET with five provenance-bearing collections and canonical region → country → city navigation;
- one-sided canonical Compare handoffs from Explore and Saved continuity surfaces;
- browser-local My Places with exact country/city identity preservation;
- provider-free City Money Profile;
- optional grounded AI explanation with deterministic fallback, including explicit reviewed-destination Explore intents;
- managed provenance-aware media, restrained source → destination presentation and historical/currency-era story exploration;
- demand-loaded frontend enhancement routing with consolidated Saved and rate-chart lazy chunks;
- a CSS custom-property integrity gate plus normalized narrow-layout spacing tokens;
- Chromium page-level 430/390/360/320 mobile coverage, 640px/320px reflow evidence, Firefox/WebKit smoke, forced-colors/reduced-motion checks and Python/PostgreSQL CI.

The original **92/100** figure is a historical planning snapshot, not a current score. Remaining work is concentrated in broader reviewed media coverage, durable account-owned SavedPlace/saved-comparison persistence, richer scenario/personalization flows, PWA/offline lifecycle work and final production evidence.

## 100/100 definition of done

The web product may be called 100/100 only when all of the following are true:

- **0 known P0 defects**.
- **0 known P1 defects**.
- all required CI workflows are green;
- Python 3.13 and 3.14 quality gates are green;
- PostgreSQL production-oriented test gates are green;
- Chromium full coverage and required Firefox/WebKit coverage are green;
- keyboard, reflow, accessibility and reduced-motion checks have no major unresolved defects;
- all financial calculations flow through canonical domain/application contracts;
- AI cannot become a source of FX, price, fee, historical, payment-prevalence or country/currency truth;
- city-to-national fallback is never silent;
- sourced factual context exposes provenance/freshness semantics;
- stale/offline FX never appears current;
- account resources are owner-scoped;
- expensive or abuse-prone endpoints have explicit protection;
- deterministic performance budgets remain green;
- canonical documentation matches shipped code;
- database and managed-media restore procedures have executable evidence;
- major runtime paths are observable;
- happy, empty, invalid, degraded and provider-failure states are intentional and tested.

## Scope boundary

The 100/100 score applies to the **current web product**.

The following are separate future product scopes and do not block web 100/100:

- native mobile application;
- native home-screen widget;
- voice interaction;
- speculative historical purchasing-power features without defensible data.

---

# Phase 0 — Truth and acceptance baseline

## PR #181 — Documentation truth sync

**Goal:** make canonical documentation accurately describe current shipped behaviour.

Update:

- `01_PRODUCT_SPEC.md`;
- `02_UX_RESEARCH_AND_FLOWS.md`;
- `04_ARCHITECTURE.md`;
- `05_DOMAIN_MODEL.md` where necessary;
- `INTEGRATIONS_AI_MEDIA.md`;
- `08_IMPLEMENTATION_ROADMAP.md`;
- README.

Must remove stale statements such as:

- Explore being purely future;
- higher-level Money Context consumers being unshipped;
- city selection being entirely future;
- saved-trip workflows being future where they already exist;
- destination-comparison text that predates Explore;
- README omissions for the latest Offline/Explore/Camera-to-trip flows.

**Merge acceptance:**

- no code behaviour change;
- docs agree with code/tests;
- shipped/partial/future terminology is consistent;
- no duplicate parallel roadmap is created.

## PR #182 — Production acceptance matrix

**Goal:** define one auditable quality matrix for every major product surface.

For each major surface record expectations for:

- happy path;
- empty state;
- invalid input;
- partial data;
- stale data;
- provider failure;
- optional-system failure;
- authorization/ownership;
- idempotency where writes exist;
- keyboard;
- accessibility;
- 320px/reflow;
- no-JS where relevant;
- Chromium;
- Firefox;
- WebKit;
- PostgreSQL.

The matrix should point to tests rather than duplicate test logic.

---

# Phase 1 — Contextual AI product layer

## PR #183 — Contextual AI quick prompts

Add deterministic prompt eligibility derived from trusted current context.

Examples:

- rate explanation;
- cash/card guidance;
- payment warning;
- budget-fit explanation;
- destination comparison.

Rules:

- no empty chatbot;
- only 2–4 relevant prompts;
- prompt eligibility is deterministic;
- a prompt is hidden when required trusted context is absent;
- prompts never manufacture missing facts.

## PR #184 — Structured AI insight contract

Introduce one validated structured response shape:

- `short_answer`;
- `key_factors[]`;
- `watch_out_for`;
- `next_step`.

Requirements:

- strict schema validation;
- bounded field lengths;
- bounded list sizes;
- deterministic context snapshot;
- malformed output fails closed;
- model failure leaves deterministic result intact.

## PR #185 — AI grounding guard

Add application-level validation that rejects generated output which contradicts trusted structured context.

Validate against:

- source/destination currency;
- conversion amount/rate;
- effective date;
- city/country scope;
- reviewed price anchors;
- payment-context facts.

Generated text is optional presentation, never financial truth.

## PR #186 — Smart result summary

Add one concise result implication after successful conversion.

Priority:

1. deterministic template;
2. deterministic context-enriched template;
3. AI only when it materially improves explanation.

Never produce:

- investment-style language;
- “good/bad time to exchange”;
- unsupported “cheap/expensive” judgments;
- unsupported affordability claims.

**Implemented first slice:** deterministic trust-first summary on every successful conversion, with optional reviewed local-price/payment context only after Money Context provenance/freshness gates. Historical, stale and exact 1:1 semantics outrank enrichment; unsupported price-equivalent states fail closed.

## PR #187 — AI UX reliability pass

Cover:

- loading;
- cancellation;
- timeout;
- retry;
- provider disabled;
- malformed output;
- safety blocking;
- fallback;
- keyboard operation;
- screen-reader announcements;
- no layout collapse when AI fails.

**Implemented first slice:** the existing quick-prompt flow now has explicit live loading/busy semantics, scoped button disabling, latest-request-wins cancellation through the existing HTMX sync boundary, focus transfer to inserted answer/error content, deterministic timeout fallback with retry guidance, client-side transport-error recovery messaging and no-JavaScript retry wording. Browser/release-quality CI enables a deterministic runtime-AI fixture only under `APP_ENV=test`, so Chromium/Firefox/WebKit can exercise the actual interaction without an external Gemini call. Production configuration rejects that fixture outside the test environment.

---

# Phase 2 — City Money Intelligence

## PR #188 — City data-quality contract

Formalize quality rules for city-scoped `TypicalPrice` data:

- canonical City reference;
- correct country relationship;
- current compatible currency;
- normalized category/unit;
- positive valid amount;
- source name;
- valid provenance URL;
- observation date;
- freshness policy;
- duplicate semantics.

Do not introduce a parallel city-money datastore.

**Current production slice:** one reusable `apps/culture/price_quality.py` contract now owns the 730-day freshness policy, stable issue codes and canonical category→unit mapping. `TypicalPrice` stores that normalized unit, normalizes labels/source names and canonical city display text on save, rejects published legacy city text without a canonical `City`, rejects inactive/wrong-country city references, stale/future observations, missing/invalid provenance and non-current primary currency at validation time, and detects duplicate canonical scope/category/unit/label/date observations after whitespace/case normalization. Database constraints enforce category↔unit pairs, published canonical-city scope and exact canonical city/national observation identities. Existing rows are migration-backfilled; no parallel datastore is introduced.

## PR #189 — City coverage health tooling

Add a management/report command exposing, per city:

- currency;
- total supported categories;
- fresh categories;
- stale categories;
- national fallback categories;
- provenance gaps;
- coverage score/summary.

The score is a data-maintenance diagnostic, not a user-facing cost-of-living score.

**Current production slice:** `apps/culture/city_health.py` now derives deterministic health rows for active canonical cities using the #188 quality evaluator and current primary-currency mapping. `report_city_coverage` exposes stable text and `--json` output with optional country/city/as-of filters. Four core categories form the score denominator: fresh city evidence contributes 25 points per category, fresh national fallback contributes 15 only when direct fresh city evidence is absent, and stale/provenance-broken rows contribute zero while remaining visible as maintenance gaps. The score is operational only and must not be surfaced as affordability, value or destination ranking.

## PR #190 — Curated city dataset wave 1

Prioritize depth over breadth.

Initial European/Nordic set should have enough reviewed categories to support actual money context, not token one-row coverage.

Candidate set:

- Helsinki;
- Turku;
- Stockholm;
- Copenhagen;
- Oslo;
- Berlin;
- Amsterdam;
- Paris;
- London;
- Barcelona;
- Rome;
- Tokyo.

Exact cities may change based on defensible source availability.

**Current production slice:** the first reviewed wave deliberately ships six deep city scopes rather than twelve shallow ones: Helsinki, Turku, Stockholm, Copenhagen, Oslo and Berlin. Each canonical `City` has four fresh city-specific `TypicalPrice` anchors covering coffee, casual meal, transit and a fixed grocery basket, for 24 rows total. Coffee/meal/grocery ranges are city-level contextual snapshots with explicit provenance, review/observation date, medium confidence and transparent fixed-basket derivation; transit anchors use the relevant official operator with authoritative/high-confidence classification. Every seeded row is validated through the existing #188 `TypicalPrice.full_clean()` contract before persistence, uses the country's current primary currency, and reaches 4/4 direct fresh core categories in the #189 maintenance health diagnostic without national fallback. This dataset does not create affordability, value or cost-of-living rankings, and it does not promote national evidence to city evidence.

## PR #191 — Curated city dataset wave 2

Expand to high-value Asia/Oceania/North America destinations with the same quality contract.

No city ships simply to increase destination count.

**Current production slice:** the second reviewed wave adds Tokyo, Singapore, Toronto and Auckland after source-quality review rather than filling a geographic quota. Singapore, Toronto and Auckland each seed four direct city-scoped core anchors; Tokyo reuses the already-reviewed authoritative Tokyo Metro fare and adds city-specific coffee, casual-meal and fixed grocery-basket anchors. All four cities therefore reach 4/4 direct fresh core coverage with current primary currencies, HTTPS provenance and no national fallback. Everyday-price rows remain explicitly approximate/contextual with medium confidence, while transit rows remain authoritative/high-confidence and cite the relevant public transport authority. The wave adds SGD, CAD and NZD reference relationships from central-bank sources and continues to validate every new city-price row through the existing #188 quality contract. Sydney is intentionally not included in this slice because the reviewed official fare source did not provide a sufficiently stable machine-verifiable fare table for an authoritative seeded anchor.

## PR #192 — City Money Profile UX

Create a coherent city money profile using existing canonical context:

- explicit city scope;
- current local currency;
- reviewed everyday-price anchors;
- national fallback labels;
- freshness;
- payment context;
- Convert;
- Budget;
- Compare;
- Save/My Places handoff.

**Current production slice:** a dedicated provider-free city profile now resolves one canonical active city through the current-primary currency relationship and the existing `build_destination_context()` contract. A profile exists only when direct city evidence survives the same freshness/provenance rules; national data alone cannot manufacture a city page. Visible price rows retain explicit city versus national-fallback scope, observation date, source class, confidence and provenance, while country-level payment guidance is shown only when reviewed. Convert, destination-budget and destination-comparison handoffs preserve the canonical city token. Reviewed country/city identity can now be saved through browser-local My Places and reopened from Saved & recent; durable account-owned SavedPlace persistence/sync is still future work.

## PR #193 — City/national fallback trust audit

Add invariants proving:

- national-only evidence cannot create a city-specific claim;
- national fallback is always visible as fallback;
- wrong-currency price anchors are excluded;
- stale-only context fails closed;
- city references cannot cross country boundaries.

**Current production slice:** the fallback trust audit is executable and closes the City Money Intelligence trust boundary. National-only evidence may support a selected city only as explicitly labelled national fallback; it cannot create an Explore city card or City Money Profile. Wrong-currency and stale price rows are excluded from visible current context. Cross-country canonical city references are rejected by the model quality contract, and the context query now defensively accepts only same-country canonical city rows or explicit national rows even if invalid data reached storage by bypassing `full_clean()`. Dedicated regressions cover national-only scope, fallback presentation, wrong currency, stale-only city context, health/Explore fail-closed behaviour and cross-country storage corruption.

**Phase 2 exit:** the two reviewed city-data waves, City Money Profile and fallback trust audit complete the planned City Money Intelligence phase at the canonical **95/100** milestone without introducing a cost-of-living or affordability ranking.

---

# Phase 3 — Explore 2.0

## PR #194 — Explore collections domain

Add deterministic, provenance-aware collection composition for categories such as:

- city money profiles;
- currency stories;
- cash/card behaviour;
- shared-currency countries;
- recently reviewed destinations.

Do not invent “popular” collections without real evidence.

**Current production slice:** a provider-free collection composition layer now derives five neutral collection kinds entirely from existing reviewed domain state. City-profile items require direct city evidence; currency-story items require published reviewed stories and valid provenance; cash/card items require reviewed current-country payment guidance; shared-currency items require at least two current-primary country relationships with valid source URLs; recently reviewed destinations are ordered by evidence date rather than popularity or value. Every collection item carries explicit provenance evidence, bounded deterministic ordering and stable scope identity, and empty/invalid collections fail closed. No collection performs an FX/AI request, adds a geography model or creates a ranking/affordability score. These collections are now rendered through the shipped regional Explore UX described below, with canonical region → country → city navigation and preserved provenance.

## PR #195 — Regional Explore UX

Add region → country → city discovery using canonical geographic/domain identities.

Do not build a second geography model.

**Current production slice:** Explore now renders the #194 evidence-backed collections and a premium regional directory on one provider-free surface. Regional grouping reuses canonical `Country.region` / `Country.subregion` plus canonical `City.country` relationships; the deterministic reference seed supplies those fields for the reviewed production destinations and unknown geography degrades into an explicit final “Other reviewed destinations” group instead of disappearing. The view composes destination scopes once and reuses that tuple for regional navigation and collections, avoiding duplicate discovery/provider work. Collection provenance is progressively disclosed, region navigation works without JavaScript, and country/city actions preserve canonical converter/profile scope. Optional collection or regional composition failures degrade locally while the reviewed destination fallback remains usable. The surface has dedicated cross-browser interaction, axe, reflow, reduced-motion and forced-colours evidence.

## PR #196 — Same amount across destinations

Allow one source amount to be viewed across several explicit destinations.

Each destination independently retains:

- trusted FX observation;
- effective date/provider semantics;
- local currency;
- city/national context scope;
- provenance.

No winner, PPP claim, direct “cheapest” ranking or generic cost-of-living score.

**Current production slice:** shipped as a separate Explore decision surface for two to four explicit destinations. It reuses canonical current conversion/Money Context composition, preserves destination order and independent provider/date/scope/provenance semantics, allows partial success, and never derives a winner, PPP or affordability ranking.

## PR #197 — Explore → Compare handoff

Allow selected Explore destinations to open the canonical Destination Comparison flow.

No comparison business logic belongs in Explore.

**Current production slice:** shipped. Reviewed Explore country/city rows and destination-oriented collections can seed exactly one canonical comparison side. City tokens are preserved, Destination B remains unset and all comparison assumptions stay owned by the canonical Compare flow.

## PR #198 — Explore → My Places handoff

Add save-place interaction contract; durable persistence is completed in the personalization phase.

**Current production slice:** shipped as browser-local persistence. Reviewed country/city rows use the versioned local SavedPlace contract with validation, dedupe and bounded retention; no-JS/storage-unavailable states do not render fake controls. Durable account ownership/sync remains future work.

## PR #199 — Explore → contextual AI

Expose only prompts grounded in reviewed Explore context.

AI must never create discovery cards or substitute for missing data.

**Current production slice:** shipped as an explicit POST over one reviewed destination plus one server-approved intent. The server revalidates the destination against current Explore state, rebuilds trusted DestinationContext and sends only a bounded structured fact packet through the existing validated AI stack. Explore GET remains provider-free; provider failure returns deterministic grounded fallback.

## PR #200 — Explore quality pass

Test and polish:

- zero results;
- one result;
- sparse data;
- stale data;
- partial city coverage;
- optional failure;
- 320px;
- keyboard;
- Firefox/WebKit;
- no-JS where appropriate.

**Current production slice:** the major Explore/City/Same Amount quality pass is shipped: premium hierarchy, reduced CTA duplication, 320/360/390/430 mobile coverage, keyboard/axe checks, no-JS continuity, forced-colors/reduced-motion handling and Chromium full + Firefox/WebKit smoke coverage.

---

# Phase 4 — Currency and cultural history

## PR #201 — Currency story entry point

Add a progressive-disclosure entry from a current conversion/context into currency history.

**Current production slice:** shipped through the Money & culture / historical-series handoff. Currency history stays progressive-disclosure and reuses existing temporal/provenance contracts rather than creating a second historical truth path.

## PR #202 — Previous-currency story

Surface:

- predecessor currency;
- validity period;
- transition timing;
- concise sourced context;
- relevant historical FX links.

No unsourced macroeconomic explanation.

**Current production slice:** Money & culture now separates temporal country–currency eras from independently reviewed story moments, keeps source/destination era identity explicit and preserves opt-in historical replay. No unsourced causality or purchasing-power inference is introduced.

## PR #203 — Currency timeline

Compose:

- currency eras;
- dated transitions;
- selected historical observations;
- provenance.

**Current production slice:** Historical Series now exposes factual chronological range landmarks plus selected/minimum/maximum/last observations and stronger Then & Now semantics. The adjacent Money & culture era/story surface supplies reviewed temporal context without inventing currency events.

## PR #204 — Historical media integration

Only reviewed and adequately licensed/attributed media may support timeline/Then & Now surfaces.

Historical media must be temporally scoped.

**Current production slice:** managed media already enforces provenance/review and graceful omission when suitable media is absent. Broader authentic archival coverage remains future breadth work; historical FX is never converted into an unsourced historical purchasing-power claim.

## PR #205 — Cultural-history portal

Create one compact exploration surface for:

- cultural snapshot;
- currency story;
- previous currency;
- payment culture;
- money etiquette;
- travel-money tip;
- sourced memorable fact.

## PR #206 — Bilateral cultural experience

Keep source and destination culturally legible together without creating two unrelated visual themes.

**Current production slice:** successful converter results now include a restrained Source → Destination identity rail using existing presentation context and country themes. Reviewed destination media can accompany the result without becoming financial truth; missing media leaves a clean, complete converter.

## PR #207 — Historical semantics audit

Enforce the invariant:

**historical FX is not historical purchasing power.**

Audit code, templates, copy and tests for misleading language.

**Current production slice:** the historical-series and Money & culture surfaces now state and test this boundary directly. Factual FX extrema/timeline landmarks remain reference-rate observations, not affordability or purchasing-power claims.

---

# Phase 5 — My Places and personalization

## PR #208 — SavedPlace domain

Add canonical owner-scoped saved-place persistence:

- owner;
- country;
- optional canonical city;
- created timestamp.

Constraints:

- city belongs to country;
- owner duplicates prevented;
- ownership enforced.

**Current status:** this durable account-owned domain is **not shipped**. What is shipped is a browser-local versioned SavedPlace contract plus Saved & recent continuity. Sign-in does not silently migrate or sync those local places.

## PR #209 — My Places UX

Provide:

- Convert;
- Budget;
- Compare;
- Explore;
- Create trip;
- Remove.

## PR #210 — Explicit user preferences

Persist only explicit user-selected defaults such as:

- home currency;
- preferred language;
- answer-detail preference;
- safe reusable planning defaults.

Do not silently infer a sensitive travel/financial profile.

## PR #211 — Browser-local → account migration

Define explicit, idempotent migration for supported browser-local state.

Requirements:

- deduplication;
- conflict behaviour;
- user ownership;
- rollback-safe writes.

## PR #212 — Actionable history

From recent history allow:

- repeat;
- compare;
- save;
- create trip;
- open destination.

Historical records preserve original requested/effective-date semantics.

**Current production slice:** recent conversions already support canonical Repeat and one-sided destination Compare handoffs; Reverse/Swap remains a separate tertiary action and requested/effective-date meaning is preserved. Save/create-trip/open-destination expansion is still future work where no canonical handoff exists.

## PR #213 — Next-trip defaults

Reuse only stable preferences and explicit reusable assumptions.

Never automatically copy prior-trip spend, receipt information or destination-specific financial history into a new trip.

---

# Phase 6 — Scenario ecosystem completion

## PR #214 — Transparent budget presets

Add understandable editable presets/categories without opaque “cheap/luxury” scores.

## PR #215 — Real Payment Estimate → Budget handoff

Allow explicit payment assumptions to feed budget planning without confusing reference FX with executable card/ATM outcomes.

## PR #216 — Shopping calculation domain

Reuse `SavedScenarioKind.SHOPPING`.

Support:

- item price;
- shipping;
- explicit known fees;
- optional user-entered FX markup.

## PR #217 — Shopping UX

Unknown duties/taxes/issuer/merchant fees remain explicitly unknown unless authoritative or user supplied.

## PR #218 — Shopping save/reopen

Reuse SavedScenario ownership and observation contracts.

No parallel shopping persistence subsystem.

---

# Phase 7 — Pre-trip reminders and notifications

## PR #219 — Notification preference domain

Explicit opt-in only.

Represent:

- enabled state;
- notification type;
- timezone;
- cadence;
- supported delivery configuration;
- disable/delete semantics.

## PR #220 — Pre-trip reminder

Use explicit saved travel dates to prompt re-open/re-check near departure.

Do not provide speculative exchange-timing advice.

## PR #221 — Context/offline freshness reminder

Notify only when a saved trip's reviewed context or offline pack is materially stale before travel.

## PR #222 — Scenario rate alert

User-defined threshold against a saved scenario observation.

Language must remain informational and scenario-oriented.

## PR #223 — Notification reliability and deduplication

Cover:

- idempotency;
- last-sent state;
- retries;
- disabling;
- deletion;
- timezone boundaries.

---

# Phase 8 — PWA and offline production readiness

## PR #224 — PWA manifest

Add installable web-app identity and managed icon assets.

## PR #225 — Service-worker foundation

Define explicit cache rules.

Sensitive account pages must not be cached accidentally.

## PR #226 — Offline app shell

Provide navigation and clear offline state without pretending data is live.

## PR #227 — Offline active-trip view

Support read-only access to:

- saved trip;
- stored FX observation;
- immutable budget baseline;
- remaining budget;
- captured reviewed destination context.

## PR #228 — Offline freshness semantics

Relevant values must clearly resolve to one of:

- live;
- stored;
- stale;
- offline snapshot.

## PR #229 — Offline pack lifecycle

Add:

- version;
- generated timestamp;
- refresh;
- outdated state;
- replacement semantics.

---

# Phase 9 — Premium visual product pass

## PR #230 — Destination photography coverage

Expand reviewed contemporary destination photography where it adds useful context.

Do not add imagery for density alone.

## PR #231 — Responsive media derivatives

Ensure appropriate image dimensions, responsive sources and loading policy.

## PR #232 — Focal-point and crop audit

Validate mobile/tablet/desktop crops.

## PR #233 — Bilateral visual system

Add restrained source/destination distinction using typography, atmosphere and reviewed media rather than decorative gimmicks.

## PR #234 — UI simplification

Remove:

- duplicate CTAs;
- redundant labels;
- repeated navigation;
- low-value cards;
- explanatory copy that no longer earns its space.

## PR #235 — Empty/degraded state perfection

Every optional subsystem must have intentional states for:

- absent;
- unavailable;
- stale;
- partial;
- provider failure.

---

# Phase 10 — Accessibility completion

## PR #236 — Full keyboard audit

All primary workflows must complete without a pointing device.

## PR #237 — Screen-reader semantics

Audit:

- conversion results;
- validation errors;
- live updates;
- AI states;
- Camera flow;
- comparison;
- trip actions.

## PR #238 — Reflow and zoom

Validate narrow layouts and relevant 200%/400% zoom behaviour.

## PR #239 — Motion, contrast and focus

Verify:

- `prefers-reduced-motion`;
- visible focus;
- contrast;
- error association;
- focus order.

---

# Phase 11 — Security and failure engineering

## PR #240 — Provider failure matrix

Simulate:

- FX timeout;
- FX 4xx/5xx;
- malformed FX;
- AI timeout;
- malformed AI;
- destination enrichment failure;
- managed-media/storage failure.

Optional failures must not corrupt conversion truth or saved state.

## PR #241 — Security audit

Review:

- CSRF;
- signed tokens;
- replay protection;
- IDOR/owner scoping;
- redirects;
- upload parsing;
- MIME/content validation;
- cache headers;
- secrets;
- CSP/security headers.

## PR #242 — Abuse/rate-limit boundaries

Protect expensive or abuse-prone surfaces, especially:

- AI;
- Camera;
- authentication;
- comparison/context endpoints where necessary.

## PR #243 — Retry and circuit policy

Retries are allowed only where operations are safe/idempotent.

Do not perform blind provider retries inside database transactions.

---

# Phase 12 — Recovery and production operations

## PR #244 — PostgreSQL backup evidence

Add executable backup validation appropriate to production deployment.

## PR #245 — Clean restore drill

Prove:

backup → fresh database → restore → migrations/checks → smoke tests.

## PR #246 — Managed-media restore evidence

Prove object-storage versioning/restore semantics for managed media.

## PR #247 — Measured RPO/RTO contract

Document measured recovery expectations rather than aspirational numbers.

---

# Phase 13 — Performance

## PR #248 — Query-budget audit

Set/query budgets for critical surfaces:

- converter;
- Explore;
- returning home;
- saved trip;
- comparison;
- city profile.

Prevent N+1 regressions.

## PR #249 — Real-media performance audit

Measure actual curated photography, not empty fixtures.

## PR #250 — Final CSS/JS budgets

Keep deterministic bundle budgets.

Do not increase them just to make CI pass.

## PR #251 — Slow-device/slow-network browser pass

Test critical travel flows under constrained conditions.

## PR #252 — Runtime Web Vitals

Collect LCP/INP/CLS only if privacy and operational design are proportionate.

---

# Phase 14 — Observability and product evidence

## PR #253 — Runtime observability

Measure at minimum:

- conversion success/failure;
- provider latency/failure;
- destination-context availability;
- AI success/fallback;
- Camera failure rate;
- stale-context rate.

## PR #254 — Structured error correlation

Add safe correlation identifiers without leaking financial/private content.

## PR #255 — Privacy-conscious product analytics

Track only value-oriented events such as:

- conversion complete;
- context opened;
- comparison;
- scenario saved/reopened;
- Camera confirmed;
- spend added;
- offline pack use;
- Explore handoff.

## PR #256 — Trip-cycle metrics

Primary retention evidence:

- saved trip → reopen;
- pre-trip re-check;
- active-trip usage;
- next-trip reuse.

Do not optimize the product around generic DAU.

---

# Phase 15 — Completeness features

## PR #257 — Shareable conversion card

Include enough source/effective-date/provider context that a shared number cannot masquerade as permanently current.

## PR #258 — Shareable travel-money card

Share only explicitly selected, non-sensitive context.

## PR #259 — Saved comparison

Persist canonical comparison inputs and user intent, not a duplicated calculation engine.

## PR #260 — Reopen comparison

Current reference values are recalculated only through explicit user action and the canonical comparison path.

---

# Phase 16 — Final release certification

## PR #261 — Full production regression

Feature freeze.

Run the full acceptance matrix against:

- PostgreSQL;
- Python 3.13;
- Python 3.14;
- Chromium;
- Firefox;
- WebKit;
- keyboard;
- accessibility;
- constrained network;
- optional services disabled;
- provider failures.

## PR #262 — Zero-P1 cleanup

Fix-only PR.

Exit criteria:

- P0 = 0;
- P1 = 0.

## PR #263 — Final documentation and runbook

Finalize:

- architecture;
- deployment;
- backup/restore;
- incident response;
- AI trust boundaries;
- data refresh;
- media provenance;
- developer onboarding.

## PR #264 — Production release candidate

Deploy an RC and smoke the complete user loop:

Convert → Context → Budget → Save → Reopen → Re-check → Camera → Spend → Offline → Explore → Compare.

## PR #265 — 100/100 certification

No new feature work.

Record measured evidence for the release scorecard.

Required categories:

- financial correctness — 100;
- trust/provenance — 100;
- reliability — 100;
- security — 100;
- accessibility — 100;
- core UX — 100;
- city/context quality — 100;
- AI boundaries — 100;
- offline semantics — 100;
- performance gates — 100;
- documentation — 100;
- operations/recovery — 100.

---

# Merge gate for every PR

No PR merges until all applicable conditions pass:

1. the PR has one coherent scope;
2. business logic is not duplicated;
3. domain invariants have tests;
4. happy, empty, invalid and degraded paths are covered;
5. ownership/security is covered for persistence;
6. idempotency is covered for retryable writes;
7. Python quality is green;
8. frontend quality is green;
9. required merge quality is green;
10. Chromium required coverage is green;
11. relevant Firefox/WebKit coverage is green;
12. PostgreSQL gate is green;
13. documentation reflects only code that is actually shipped in the PR;
14. performance budgets are not weakened without measured justification;
15. the final diff is reviewed after the last fix commit;
16. post-merge `master` is verified again.

# Expected score progression

| Milestone | Target |
| --- | ---: |
| Current baseline | 92/100 |
| Documentation + AI product layer | 94/100 |
| City Money Intelligence | 95/100 |
| Explore 2.0 | 96/100 |
| Currency/cultural history | 96.5/100 |
| Personalization/scenario completeness | 97/100 |
| Notifications + PWA/offline | 97.5/100 |
| Premium visual + accessibility | 98.5/100 |
| Security + recovery + performance + observability | 99.5/100 |
| Full regression + zero P1 + RC evidence | 100/100 |

# Execution principles

Throughout this plan:

- preserve `ConversionResult` and canonical domain/application contracts as financial truth;
- keep Decimal arithmetic;
- never equate historical FX with historical purchasing power;
- keep optional enrichment fail-open relative to valid conversion;
- keep AI explanatory and downstream of trusted structured data;
- reuse Money Context Engine rather than creating feature-specific context systems;
- reuse SavedScenario rather than creating parallel persistence for trip/budget/shopping;
- keep city/national scope explicit;
- prefer depth and provenance over broad shallow datasets;
- merge one coherent PR at a time;
- update canonical docs only when behaviour has actually shipped.
