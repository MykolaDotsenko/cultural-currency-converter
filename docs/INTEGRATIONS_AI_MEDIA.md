# Integrations, AI and Media

This document describes the main external trust boundaries. Exact provider versions, endpoints and configuration live in code and environment settings.

## Integration principle

External data should enter the product through a small project-owned boundary:

```text
external response
→ transport/validation
→ normalized project-owned value
→ application/domain use
```

Do not spread provider-specific payload shapes through views, templates or domain models.

## Runtime FX

Frankfurter is the current runtime FX provider.

The exchange layer owns bounded timeout/retry behaviour, normalization, attribution, requested/effective-date semantics, historical coverage and cache/stale behaviour.

A successful HTTP response is not sufficient; validate semantic payloads before use or caching.

## Country/currency metadata

REST Countries is currently an import/reference source rather than a normal page-request dependency.

The adapter treats provider data as untrusted input: request timeouts must be positive, each response page is capped at 2 MiB before JSON parsing, malformed JSON/shape/pagination failures are normalized to a project-owned source error, and ISO/currency identifiers must satisfy canonical ASCII alphabetic shapes before entering normalized snapshots.

Normalize country/currency data locally so the product can preserve stable identity, temporal relationships and controlled reconciliation during upstream changes.

## Authoritative economic context

World Bank, Eurostat and OECD are **ingestion sources**, not normal conversion-request dependencies.

The normalized `EconomicObservation` contract stores country scope, indicator/category, value/unit, benchmark meaning, period/frequency, observation status, dataset identity, source URL and retrieval time. `sync_economic_context` completes external fetch/validation before opening the database transaction; a requested multi-source sync fails before writes if any source fails.

Current selection rules are deliberately semantic rather than “newest number wins”:

- Eurostat HICP is preferred for recent year-over-year inflation where available; World Bank CPI inflation is the global fallback.
- OECD comparative price-level index is preferred for price-level context where available; World Bank price-level ratio is the global fallback.
- provider-specific benchmark meaning is retained (for example OECD = 100 versus United States = 1) and never normalized into an invented universal score.
- bounded freshness windows suppress old macro rows instead of presenting them as current context.

These indicators are broad statistical context only. They must not replace reviewed merchant-price observations, executable payment quotes, FX truth, cost-of-living rankings or historical purchasing-power evidence.

## Public holiday context

Nager.Date Community v4 is an **ingestion source**, not a request-path dependency.

`sync_public_holidays` fetches the requested country/year scopes before opening the database transaction, validates country/date/scope/type fields, then reconciles cached `PublicHolidayObservation` rows atomically. Reconciliation republishes returned rows and unpublishes Nager.Date rows that disappeared from a re-fetched year.

The generic destination UI intentionally shows only `nationalHoliday=true` records. Community v4 can describe first-level subdivision scope, but the current canonical City model does not carry a verified ISO 3166-2 subdivision identity, so subdivision-only holidays are stored for future use and excluded from country/city presentation.

Holiday evidence may support wording such as “public holiday today/upcoming; opening hours may differ”. It must not claim that a particular bank, shop, ATM, transport service or venue is closed/open because the holiday API does not provide entity-specific opening hours.

## Open Food Facts product identity

Open Food Facts is used only for **explicit barcode-driven product identity context** in Shopping. The integration is pinned to the current v3.6 product-read API and requests a deliberately small field set: code, product name, brands, quantity and categories.

Runtime rules:

- normal Shopping GET/POST does not call Open Food Facts;
- a request happens only after an explicit barcode lookup;
- positive product identities are server-cached for seven days; not-found responses are cached for one hour;
- a shared-cache 12 lookups/minute guard stays below the documented 15 product reads/minute/IP upstream limit;
- successful identity is carried into the Shopping submit by a signed 24-hour token so the FX calculation does not trigger a second product lookup;
- provider failure, rate limiting, invalid/tampered token or missing product never blocks the core Shopping calculator.

Open Food Facts supplies no price to the Shopping domain. Item price, shipping, known fees and FX markup remain explicit user inputs. Community product data can be incomplete and must retain Open Food Facts attribution. The database is reused under ODbL; this slice does not reuse product images, avoiding a separate CC BY-SA image-licensing surface.

## Editorial/cultural sources

Curated cultural, payment, typical-price and story content should keep enough provenance to explain source, observation/verification time, scope and confidence.

Wikidata and similar services are candidate/research sources rather than automatic runtime truth.

## Premium photography strategy

The product uses **managed realistic photography**, not release-owned cartoon country illustrations.

Preferred hierarchy:

```text
high-quality owned/licensed contemporary photo
→ high-quality sourced editorial photo
→ authentic archival/heritage media for historical surfaces
→ no image
```

“No image” is an intentional valid state. Do not fill a premium layout with weak stock, cartoon fallback art or synthetic-looking placeholders merely to occupy a media slot.

Country hero and country teaser selection is restricted to reviewed, non-generated `contemporary_photo` assets.

Destination supporting roles are explicit managed-media roles:

- `everyday_value` — atmosphere paired with reviewed price observations;
- `payment_culture` — atmosphere paired with reviewed payment guidance;
- `local_detail` — supporting editorial detail shown only when the destination has reviewed context.

For these supporting roles, reviewed sourced media is preferred. Explicitly labelled generated editorial imagery may be used as atmosphere when it passes the normal review/publication gate, but it is never evidence for a price, payment claim or local custom. The sourced text/data provenance remains authoritative.

The curated external-media manifest is intentionally sourced-only for destination supporting roles. Generated supporting imagery, when used, belongs to the separate generated-media review workflow rather than being represented as an external sourced candidate.

## Media pipeline

Managed external media can come from sources such as Wikimedia Commons, Europeana, institutions or manually curated licensed/owned photography.

Prefer:

```text
candidate/source
→ rights + provenance review
→ safe managed raster copy
→ normalization/derivatives
→ editorial approval
→ publish
→ local runtime selection
```

Normal page requests should not search the web or call an image-generation service.

For a small number of editorially selected production assets, the project can use a curated manifest plus an explicit operator command. The command may download from a narrow allowlisted source, but it remains outside normal request handling and never auto-approves or auto-publishes the result.

Curated manifests carry explicit semantic scope rather than relying on filenames or implied geography:

- current destination media can be country-scoped and currency-neutral;
- historical comparison media is countryless, explicitly currency-scoped and temporally scoped;
- `comparison_then` manifests must use sourced historical-evidence media, never generated imagery;
- country/currency reference data is resolved before any download begins, so an unknown scope fails without network I/O.

The current showcase sourced-media slice covers P01–P04 for Finland, Japan and France. Each destination item remains an explicitly selected external source with preserved provenance; manifest inclusion never means runtime publication. The manifest now also records reviewed focal coordinates and a deterministic responsive-width family for every curated destination photograph. Finland's hero remains the 24 May 2026 Helsinki tram photograph by JIP; additional Finland sources cover a Helsinki coffee scene, an HSL ticket machine and a tram interior. France adds sourced Saint-Lazare ticket-machine and Paris Metro-interior detail alongside the existing street/pastry sources. Japan retains its sourced P01–P04 set.

Ingestion validates the allowlisted host, media type, response size, redirect target and expected upstream dimensions before the sanitizer stores a managed copy. It persists the manifest focal point on unreviewed candidates while protected reviewed/published assets remain immutable to re-ingestion.

Operator flow:

```bash
python manage.py ingest_curated_media --slug <curated-slug> --dry-run
python manage.py ingest_curated_media --slug <curated-slug>
# review source metadata/bytes/focal crop, then explicitly approve the source
python manage.py build_curated_media_derivatives --slug <curated-slug> --dry-run
python manage.py build_curated_media_derivatives --slug <curated-slug>
```

The curated derivative builder fails closed when the managed source status, semantic scope, capture interval, provenance/licence metadata, intrinsic dimensions or focal coordinates drift from the reviewed manifest. Existing derivatives are also checked for actual pixel dimensions, managed bytes/content identity and inherited provenance before an idempotent rerun may skip them. It uses only manifest-declared widths, preflights a multi-item `--all-destination` run before the first write and never auto-publishes a derivative. A database constraint enforces one derivative record per `(source, variant_width)`; its migration first detects legacy duplicates and fails explicitly rather than deleting records.

Then review each generated WebP derivative at the intended mobile/tablet/desktop crop and publish the appropriate family explicitly. When a reviewed derivative and its full-size source are both published, runtime selection prefers the derivative so an accidentally published original cannot outrank the delivery-optimized family merely by being newer. Once published derivatives exist, presentation also excludes the full-size root from the responsive `srcset`; the original remains a provenance/source asset rather than a browser delivery candidate. Presentation creates `srcset` only when at least two derivative widths are published; templates keep surface-specific `sizes` hints and intrinsic dimensions.

The runtime selector remains local/database-backed. If no reviewed published derivative exists, the product intentionally renders no destination image.

The current converter result can compose reviewed destination hero/supporting media beside deterministic financial/context content. This is presentation-only: focal-point crops, intrinsic dimensions, attribution and licence disclosure come from managed-media metadata, while missing media leaves the result complete and image-free. Source/destination identity styling never turns imagery into FX, price or payment evidence.

## File formats

Managed media validation accepts JPEG, PNG and WebP and rejects SVG ingestion.

For photographic delivery:

- retain a high-quality managed source;
- generate appropriately sized derivatives;
- preserve reviewed focal-point metadata when derivatives are created;
- publish multiple reviewed widths when a surface should use responsive delivery; presentation builds `srcset` only from published assets in the same derivative family, while the template supplies the layout `sizes` hint;
- prefer modern compressed delivery such as WebP where supported by the current pipeline;
- preserve intrinsic dimensions and focal/composition information.

SVG remains suitable for interface icons and small vector marks; it is not used as large editorial country imagery.

## Media quality bar

Before publishing a destination image, check:

- realistic and contemporary when used as current country atmosphere;
- strong composition and sufficient resolution;
- natural, premium editorial treatment;
- no obvious stock cliché or country stereotype;
- no misleading logos, text or manipulated factual cues;
- rights/provenance are sufficient;
- licence attribution is visible and links to the source/licence where available;
- managed normalization/resizing is disclosed when the licence requires change indication;
- useful alt text when the image carries meaning.

## Historical media

Historical surfaces use sourced archival photography, documents, currency objects and institutional/heritage imagery as evidence. Historical-evidence roles (`comparison_then` and `historical_timeline`) reject generated media at publication and selection time.

Then & Now can render optional `comparison_then` media beside the selected historical observation. That asset must be explicitly scoped to the quote currency and its temporal range must include the selected observation date; the product does not infer a country from a shared currency such as EUR. Curated ingestion preserves that same contract by allowing a blank country scope plus an explicit currency code and temporal metadata.

Historical candidate ingestion records that scope before the external search result becomes a review candidate. For example:

```bash
python manage.py ingest_media_candidates \
  --source wikimedia \
  --query "Tokyo 1998 street" \
  --role comparison_then \
  --kind archival_photo \
  --currency JPY \
  --valid-from 1998-01-01 \
  --valid-to 1998-12-31 \
  --date-precision year \
  --dry-run
```

Remove `--dry-run` only after reviewing the query/source intent. Historical-evidence roles require a non-generated archival/artwork/heritage/map kind plus explicit temporal precision and scope; `comparison_then` additionally requires currency scope. Invalid scope is rejected before external network search.

Temporal precision should be honest. A visually attractive but misleading historical image is worse than no image. Missing or malformed historical media is non-fatal and leaves the FX comparison intact.

## AI role

AI is optional synthesis, not a source of FX rates, historical observations or published factual truth.

Current runtime behaviour remains server-side, explicit, structured, validated and AI-independent for the core conversion path.

## AI interaction contract

A useful shorthand is: **truth is deterministic; experience may be AI-shaped**.

AI may:

- summarize trusted conversion/context packets;
- explain which grounded factor matters most;
- format concise cultural or historical context;
- compare destinations only from normalized comparable inputs;
- propose context-aware follow-up questions;
- personalize wording within explicit user-controlled context.

AI must not invent rates, price anchors, payment prevalence, fees, historical observations or country/currency relationships.

For quick prompts and insight panels, use bounded structured output rather than open-ended prose. The current runtime contract is schema-versioned and contains `short_answer`, `key_factors`, `watch_out_for` and `next_step`. Every section is a grounded text object with one or more supporting fact IDs; generated prose without a valid factual support path is rejected. The deterministic fallback returns the same structure, so AI availability cannot change the surrounding UI contract.

The conversion quick-prompt slice remains signed-conversion-snapshot based. The UI never accepts an arbitrary chatbot prompt: it posts a server-defined `prompt_id`, the endpoint re-validates whether that intent is available for the signed snapshot, and the selected intent becomes part of the canonical packet hash/cache identity. Each intent declares required grounded fact IDs, and provider output is rejected if its structured sections fail to cite those facts. This keeps rate meaning, reference-vs-payment limitations, historical-date meaning and stale-cache explanations bounded by deterministic application facts.

Explore now adds a second trusted packet shape without weakening that rule. The user explicitly selects one currently reviewed canonical destination plus one server-approved intent (overview, cash/card or price evidence). The server revalidates the destination against current Explore discovery, rebuilds trusted DestinationContext, preserves city-versus-national evidence boundaries and sends only bounded structured facts to the existing validated explanation stack. Explore GET itself remains provider-free, raw prompt text is not trusted, and AI cannot create rates, prices, payment guidance, rankings, affordability or PPP truth. Budget Interpretation and Destination Comparison now use equivalent but stricter post-result contracts: the application builds one bounded structured packet per approved question only after deterministic calculation, signs the complete packet together with its capability, and accepts only that short-lived token back from the browser. Those explanation endpoints do not call the FX gateway or recompute financial results; tampering or Budget/Comparison capability crossover fails closed.

A model failure, timeout or validation failure must leave the deterministic result and sourced context intact.

Runtime interaction reliability is also part of the contract: the browser keeps the trusted conversion visible while an explanation is loading, newer prompt requests replace older in-flight requests, deterministic fallback stays usable after provider timeout, and transport failures are announced without clearing the conversion. Browser/release-quality CI covers this flow with `AI_RUNTIME_TEST_FIXTURE_ENABLED=true` only under `APP_ENV=test`; configuration rejects that fixture in production and no live Gemini request is required for browser CI.

The configured provider/model is an implementation choice and may change after quality, latency, cost and reliability evaluation.

## Multimodal inputs

Camera amount extraction and explicit confirmed-spend handoff are available for saved budget scenarios. Voice remains a future capability.

The Camera boundary is intentionally stricter than ordinary destination context:

- explicit user action is required before capture/upload;
- runtime enablement is separate from text explanation through `AI_CAMERA_EXTRACTION_ENABLED`;
- accepted uploads are JPEG/PNG/WebP up to 8 MiB and a bounded decoded pixel count;
- the application decodes, applies EXIF orientation, downsizes when needed and re-encodes the image as an in-memory JPEG before provider access, stripping original metadata;
- raw uploads and normalized images are not stored in the database/media library;
- the current external processor is the configured server-side Gemini client; browser code never receives the API key;
- the provider schema requests only amount, currency code, candidate kind and confidence, with at most six candidates;
- merchant names, people, addresses, account/card identifiers, phone numbers and surrounding receipt/menu text are explicitly outside the extraction contract;
- an explicit provider currency conflict cannot be confirmed as spend in a scenario using another currency;
- the user may correct the amount before confirmation;
- confirmation produces a short-lived scenario-scoped signed amount token and performs no write by itself;
- a confirmed Camera amount can enter trip-budget persistence only through a separate explicit POST that re-verifies token scope/currency and uses the token as the sole amount source;
- each confirmed token carries a signed unique confirmation id; that id becomes the spend submission key, so replay is idempotent without collapsing separate confirmations of the same amount;
- deterministic conversion/payment/budget math remains outside the model.

Provider failure, safety blocking, timeout or invalid structured output must leave the saved scenario untouched. No live multimodal provider call is allowed inside a database transaction.

Browser/release-quality CI exercises the complete upload → candidate → confirmation → spend handoff with a deterministic Camera extractor enabled only by `AI_CAMERA_TEST_FIXTURE_ENABLED=true` under `APP_ENV=test`. The image still passes the production decode/re-encode sanitizer and signed confirmation boundary. Configuration rejects that fixture outside the test environment, so it cannot become a production extraction provider or bypass the live-provider trust boundary.

The implemented Camera-confirmed spend handoff consumes the signed confirmation token through the existing idempotent `SavedScenarioSpendEntry` service. It persists no raw media and creates no parallel receipt ledger.

Voice, if introduced later, requires an equivalent explicit capture/minimized-retention contract.

Prefer on-device extraction when it can meet the same accuracy and trust requirements with less external data transfer.

## Generated imagery

Runtime image generation is disabled.

Generated imagery may be used as an explicitly reviewed atmospheric/supporting asset when factual authenticity is not implied. The curated country generation workflow lives in `media/00_COUNTRY_MEDIA_SYSTEM.md`. Generated assets remain classified as synthetic in media metadata and must not masquerade as archival evidence, a source for prices, or proof of payment behaviour. Authentic sourced photography remains preferable where equivalent quality and rights are available.

## AI availability and cost

AI should remain:

- explicitly configurable;
- bounded by timeout/attempts;
- server-side with no browser-exposed key;
- absent from normal live-provider CI;
- gracefully degradable.

Validated runtime explanations are persisted as a reuse/cost optimization, not as a financial truth source. Operators can bound that table with:

```bash
python manage.py prune_runtime_explanation_cache --older-than-days <days> --dry-run
python manage.py prune_runtime_explanation_cache --older-than-days <days> --batch-size <rows>
```

The retention window is deliberately explicit rather than hard-coded into application behaviour. Pruning uses a fixed cutoff and bounded batches; deleting an old explanation only means a later request may generate it again or use the deterministic fallback.

## Security/privacy at external boundaries

Avoid sending unnecessary personal/user-owned data to external providers.

Never log credentials, bearer tokens or provider secrets.

Avoid holding database locks/transactions around external network calls unless there is a concrete transactional reason.

## Adding a new integration

Before adding one, answer:

- What user problem does it solve?
- Is runtime access necessary, or can data be imported/cached?
- What is the project-owned normalized contract?
- What happens when the provider fails or changes shape?
- What provenance/licensing constraints apply?
- What tests can run without live provider dependence?
- What data leaves our system?


## Open Prices: optional dated price observations

The Shopping product identity surface can explicitly request independent
Open Prices price observations (https://prices.openfoodfacts.org/api/docs).
The first slice is web-only. No upstream price call occurs on normal Shopping
GET, product lookup alone, or calculation POST. The Shopping form still
requires a manually entered price; public price evidence is never an input to
ShoppingAssumptions, FX arithmetic or saved financial snapshots.

A request inspects at most 20 upstream rows and presents at most five proof-linked
UNIT-price records with a matching canonical barcode, positive finite Decimal
amount, explicit currency, place/country, observation date within 365 days,
and stable source record URL. Older, future-dated, ambiguous units, unproven
or foreign-product records do not qualify. This is not a current merchant
price, live quote, market average or cheapest-store ranking.

The transport enforces HTTPS origin pinning, a five-second timeout and a
256-KiB response cap with JSON Decimal decoding. The application adds a
canonical-barcode cache (12h for qualifying results, 1h empty), a shared
six-upstream-lookups-per-minute budget and neutral degraded UI. Optional
context failures never affect the Shopping FX estimate. Open Prices is
community-contributed open data under ODbL. A future mobile API extension
must maintain the same separate, read-only evidence boundary.


### Public-provider transport and provenance hardening

Open Food Facts and Open Prices share an origin-pinned HTTPS urllib transport.
It rejects off-host redirects **before** the follow-up network request (also
blocking HTTP downgrade, untrusted port, subdomain and URL user-info), rather
than relying only on the final response URL. Their initial request and final
response are also checked. Redirect failure degrades only optional content.

For Open Prices the nested location, proof and product IDs, when provided
alongside their parent foreign keys, must agree; embedded product barcode
must resolve to the same canonical product. Two-letter OSM country codes are
normalized to uppercase. Observation date windows are interpreted in UTC
consistently with the recorded retrieval timestamp. Records that disagree
across evidence fields are excluded, not silently re-attributed. See
https://openfoodfacts.github.io/documentation/docs/Open-prices/prices/prices_list/
for the current public schema.


### Outbound public-provider host allow-list

The origin-pinned opener is also applied to Eurostat (ec.europa.eu),
World Bank (api.worldbank.org), OECD SDMX (sdmx.oecd.org),
Nager.Date (nagerholidays.com), and Wikidata (www.wikidata.org).
All seven public-data HTTP integrations now reject unsafe initial URLs and
redirect destinations before any follow-up network request. Same-host HTTPS
redirects continue working; source failure is handled by each existing optional
provider error boundary. An integration test asserts actual opener wiring for
every provider, guarding against accidental reintroduction of urllib's
default unrestricted redirect behavior. This changes no FX, historical
observation or curated financial truth.


### Mobile Open Prices evidence endpoint

GET /api/v1/products/{barcode}/prices/ provides an opt-in, read-only public
API v1 adapter over the exact existing web Open Prices cache, canonical
product normalization, and verified observation *fields*. It exposes financial
Decimal observations as JSON strings with source links, UTC retrieval time
and observation date; the proof ID refers to provider evidence and is not a
claim that its actual contents have been independently authenticated.
All responses are private, no-store. Per-peer API quota protects cache reads,
while the separate global upstream budget still applies. Never auto-fill
Shopping itemPrice from community records or reinterpret them as live offers.


## Backend → frontend capability coverage contract

The user-facing Django web application uses the same application/domain services as
`/api/v1/`. The public API is primarily a stateless external-client boundary:
**do not make the Django frontend call its own public HTTP API** to add a card.
Use the canonical application services and existing view models instead.

| Trusted capability / source | Current browser surface | Remaining opportunity and boundary |
| --- | --- | --- |
| Frankfurter reference FX | Convert, historical series, side-by-side Compare, Shopping, Budget | Emphasize effective/fetched/stale/source semantics in every context handoff; never label a reference rate as an executable bank quote |
| REST Countries reference metadata | Country/currency picker, Destination Mode, Explore | More useful country money profiles; imported metadata cannot independently prove current payment/cultural behaviour |
| Reviewed CountryCurrency / City identity | Destination Mode, City Profile, Explore, My Places | Reuse canonical country/city identity and current currency when constructing a new trip; never infer city prices from national prices |
| Reviewed TypicalPrice + Money Context | Convert, Budget, City Profile, Compare, Saved Trip refresh | Make useful local-value facts more accessible at the decision point without new conversion arithmetic or false affordability claims |
| World Bank / Eurostat / OECD ingested observations | Current Money Context Lens, public conversion API v1 | Better profile/saved-trip exposure of country-scoped macro evidence, including dataset/benchmark/period; not a merchant price or a city inflation estimate |
| Nager.Date ingested public holidays | Current Money Context Lens, conversion API v1 | Reuse national-only dates for trip readiness; never imply an individual business is open or closed |
| Reviewed card/cash/ATM/tipping/DCC guidance | Convert context, City Profile, saved-scenario explicit context refresh | Put the relevant *reviewed* tip next to a payment decision; dates and country scope must remain visible |
| Open Food Facts | Shopping optional barcode lookup and product identity; read-only API v1 | Optional scanner and clearer identity-first UI; not a source of shelf prices |
| Open Prices | Explicit opt-in Shopping historical evidence and read-only API v1 | Make proof/location/date/discount evidence easier to interpret; never auto-fill Shopping's current item price |
| Gemini structured text and Camera | Optional Convert/Explore/Budget/Compare explanations; opt-in saved-trip Camera | Use bounded, signed, verified fact packets for insight placement; no AI-authored rate/price/fee or automatic spend |
| Wikimedia Commons / Europeana / reviewed media | Approved and published destination/historical imagery | Expand editorial coverage only with source, licence, crop and publication review; absent media is valid |
| In-app scenario notifications | Account-owned saved scenario preferences and inbox | Operational scheduler and measured delivery; a created preference is not itself a delivered message |
| Explicit offline/PWA snapshot | Saved Trip offline options and generic offline app shell | Keep exact stored-as-of/stale semantics; never cache private navigation HTML automatically |

### Review and regression rules

For every new integration-backed frontend feature:

1. identify the canonical provider/ingestion boundary, trusted domain data, view model,
   template, source attribution and tested happy/empty/invalid/degraded states;
2. prove useful information is actually visible in a rendered web response, not merely
   available through a model, public JSON endpoint or documentation;
3. show provenance, observation/verification date, geographic scope and uncertainty
   alongside any actionable information; no city/national scope substitution;
4. verify no extra FX or costly provider lookup occurs during provider-free GETs, and
   one optional-source failure cannot break conversion truth;
5. exercise keyboard, screen-reader naming, no-JavaScript where applicable,
   narrow reflow and at least the relevant Chromium/Firefox/WebKit smoke flows.

`config/tests/test_frontend_integration_contract.py` is a **structural wiring guard**
that checks the most important named routes, Django templates and evidence hooks.
It cannot replace rendered integration tests, browser testing or production provider
availability checks. Stronger behavioural assertions stay in the existing
`apps/culture/tests/`, `apps/exchange/tests/`, `apps/travel/tests/` and browser suites.
