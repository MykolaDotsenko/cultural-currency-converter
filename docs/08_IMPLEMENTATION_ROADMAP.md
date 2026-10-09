# Roadmap

This roadmap is active direction, not a frozen PR sequence.

Re-evaluate priorities as product value, code quality and deployment needs become clearer.

## Current baseline

The web product already includes:

- current and historical FX conversion;
- country/currency temporal modelling;
- historical trends with 1Y / 5Y / 10Y / custom ranges, anchor observations and Then & Now;
- smart country/currency filtering across current, shared and historical relationships;
- explicit-assumption Real Payment Estimate for current non-identity conversions;
- destination payment/everyday-value context;
- destination-first country/city planning that resolves into the canonical converter and preserves canonical city scope;
- side-by-side destination comparison across two explicit current scopes using one shared assumption set and canonical Money Context composition;
- deterministic budget interpretation plus account-owned saved budget scenarios, reference-rate re-check and Trip Budget Remaining;
- explicit Camera extraction/confirmation with a separate idempotent spend handoff;
- self-contained Offline Destination Pack export from saved budget scenarios;
- returning-user trip continuity on the clean converter home;
- provider-free Explore GET over reviewed country/canonical-city money context, with five provenance-bearing collections and canonical region → country → city navigation;
- Same Amount Across Destinations over two to four explicit scopes with independent FX/context provenance and no ranking semantics;
- City Money Profile with direct-city evidence requirements and explicit city/national fallback;
- canonical one-sided Destination Comparison handoffs from Explore and Saved continuity surfaces;
- deterministic culture/story content plus currency-era / historical-series timeline exploration;
- managed raster media with provenance/review and restrained destination-media composition;
- optional grounded AI explanation with deterministic fallback for conversion, reviewed Explore destinations, Budget Interpretation and Destination Comparison;
- browser-local favourites/recent conversions/My Places plus account-owned favourites/scenarios and opt-in account recent history;
- Saved & recent continuity with primary/secondary/tertiary re-entry actions and exact city-scope preservation where available;
- demand-loaded converter/picker, Saved and rate-chart enhancements with HTMX re-discovery and route-isolation checks;
- browser accessibility/reflow quality gates including 640px/320px (~200%/~400%) evidence, forced-colors and reduced-motion coverage.

The old release-owned cartoon SVG media pack has been removed.

Roadmap item numbers are stable planning IDs. When an item ships, it moves to the shipped section instead of being renumbered, so the remaining future queue can contain gaps.

## Shipped roadmap items

The following previously planned items are now part of the current product baseline:

- **#4 Country ↔ currency smart filtering — shipped.** The current picker supports country-context and currency-only choices, respects historical mode/date semantics and labels historical options; form validation rejects mismatched country/currency submissions before provider access.
- **#10 Real Payment Estimate — shipped reusable-assumption slice.** Current non-identity conversions can apply explicit FX markup plus source/destination fixed-fee assumptions through a signed trusted conversion snapshot. Signed-in users can save up to 12 owner-scoped named fee profiles for exact currency pairs; applying one changes only assumption inputs and cannot alter the signed reference conversion.
- **#23 Historical quick ranges and anchor values — shipped.** The historical-series UI supports 1Y / 5Y / 10Y / custom ranges with selected/minimum/maximum/last observations, provider/stale context and Then & Now where available.
- **Money Context Engine application contract — foundation shipped.** Trusted conversion output now composes with optional current destination context through one reusable application contract with explicit available/empty/not-applicable/degraded states. Canonical destination city scope travels through the same contract instead of using a parallel path. Budget, destination comparison, saved-trip, Camera, offline-pack, returning-home and Explore slices now consume this shared meaning; native/mobile consumers remain future work.
- **Account My Places city-link validity — shipped.** Account-owned saved cities show a City Money Profile shortcut only when current primary-currency, fresh, published, source-valid *direct city* price evidence exists. A bulk evidence query avoids N+1 view composition and prevents dead 404 links; unavailable guides retain Explore as an alternative without losing saved identity.
- **#34 Destination mode — shipped first production slice.** Manual country/canonical-city selection resolves the current primary local currency, preserves explicit city scope where available and redirects into the canonical converter. The destination entry surface makes no FX-provider call and uses no device location.

## Now: final release evidence

The large October 2026 frontend/media quality pass has already shipped:

- premium hierarchy/CTA cleanup across Explore, City Money Profile, Same Amount and Saved continuity;
- final frontend-system cleanup with a CSS custom-property integrity gate, normalized narrow-layout spacing tokens and page-level 430/390/360/320 Chromium regression coverage;
- 640px/320px reflow evidence (~200%/~400% equivalents) with additional 200% text expansion;
- stable mobile-header geometry, reduced-motion/forced-colors handling and broader browser QA;
- demand-loaded converter/picker, consolidated Saved-state and rate-chart enhancements with HTMX re-discovery;
- restrained source → destination result identity inside one Quiet Atlas Premium system;
- reviewed managed destination-media composition with provenance, focal crops, intrinsic dimensions and graceful no-media rendering;
- sourced showcase P01–P04 selections for Finland, Japan and France, each with executable reviewed focal coordinates and deterministic responsive-width plans;
- idempotent curated derivative generation plus read-only strict readiness reporting, while keeping ingestion/review/publication separate and explicit;
- stronger Historical Series chronology/Then & Now and Money & culture currency-era/story exploration;
- browser-local plus owner-scoped My Places, explicit local→account migration, durable input-only SavedComparison and canonical provider-free Reopen / explicit Re-check semantics;
- trusted Budget AI and Comparison AI over server-signed bounded fact packets derived only from already-deterministic results; AI cannot recalculate rates/prices/basket totals, fill missing coverage or rank destinations.

The remaining premium/product priorities are narrower:

- extend sourced photography beyond the Finland/Japan/France showcase wave only when a reviewed destination earns the visual slot; do not add placeholder imagery for coverage statistics;
- treat deployment publication of curated source/derivative families as explicit operational evidence: source selection in Git is not runtime readiness, and `report_curated_media_coverage --strict` is the auditable check;
- treat further focal/crop and CSS/spacing/typography edits as evidence-driven refinements rather than separate cleanup phases;
- extend durable personalization only through evidence-backed use cases; do not turn saved inputs into hidden financial truth;
- keep Budget AI / Comparison AI bounded to their shipped signed fact-packet contracts; extend intents only when the deterministic surface already owns every required fact;
- continue profiling real-media performance within the current frontend guardrails.

Do not add images simply to increase visual density, and do not duplicate backend truth in frontend-only state.

## Next: high-value product expansion

After the premium visual pass, implement the strongest remaining concepts from the original project vision. This queue contains only features that currently score **60/100 or higher** for combined user usefulness and product distinctiveness. The scores are planning aids, not permanent requirements; re-evaluate them if user evidence or implementation cost changes materially.

1. **Bilateral cultural experience — 91/100**
   - Keep source and destination culturally legible at the same time, not only financially legible.
   - Let both sides contribute useful local context such as place identity, everyday-value cues and destination atmosphere.
   - Preserve one coherent premium interface rather than turning the page into two unrelated themes.
   - **Current production slice:** successful converter results now render a restrained Source → Destination identity rail from existing country/currency presentation context. Reviewed destination hero/supporting media can sit beside deterministic facts with provenance and graceful no-media fallback. This is presentation-only: no new financial or media truth is created.

2. **Currency story / previous-currency exploration — 88/100**
   - Add a clear progressive-disclosure entry point from a selected country/currency into its currency history.
   - Reuse the existing temporal country/currency model, archived currencies, historical FX, Then & Now and provenance rules.
   - When a country changed currency, explain the transition and expose relevant historical context without implying historical purchasing power.
   - **Current slice:** the canonical Money & culture surface now separates country–currency era records from independently published story moments, keeps source/destination era identity explicit, collapses provenance behind inspectable disclosures and states the historical-purchasing-power boundary directly. Historical converter suggestions remain opt-in: the user's explicit currency is never silently replaced, and choosing a suggested historical currency reuses the existing canonical replay action for the selected date.

3. **Travel-money companion layer — 88/100**
   - Expand destination context around practical money use rather than becoming a generic tourism guide.
   - Prioritize what an amount roughly means locally, payment habits, cash/card/ATM guidance, tipping/customs and repeat-trip usefulness.
   - Keep claims sourced, scoped and current; optional enrichment must remain non-blocking for conversion.

5. **Historical guide / currency timeline — 80/100**
   - Build a deeper historical exploration layer from the existing historical FX and Then & Now foundations.
   - Prefer concise timelines, currency-era transitions, sourced archival media and provenance over encyclopedia-style long-form content.
   - Keep historical FX separate from historical purchasing-power claims.
   - **Current slice:** Historical Series now exposes chronological range anchors and stronger Then & Now semantics over the published reference-rate series, while Money & culture provides the adjacent currency-era/story layer. Both surfaces keep reference FX, temporal currency relationships and sourced editorial history distinct; neither infers historical purchasing power or causality.

6. **Favourite countries / My Places — 76/100**
   - Let users save countries/places independently of a specific conversion pair.
   - Use saved places as shortcuts into common source/destination flows and destination money context.
   - Define browser-local versus account-owned persistence and migration/sync behaviour before shipping.
   - **Current slice:** reviewed Explore country/city rows now support two explicit persistence modes: versioned browser-local My Places for anonymous use and owner-scoped `SavedPlace` records when signed in. Saved & recent reopens canonical Converter, Budget, City Profile and one-sided Destination Comparison flows while preserving city scope. Sign-in does not silently migrate existing browser places; migration is a separate explicit idempotent action. Account records persist canonical place identity only and resolve the current primary currency again at read time.

7. **Subtle bilateral visual styling — 74/100**
   - Give source and destination distinct but restrained visual identity inside the same Quiet Atlas Premium system.
   - Prefer typography, tonal atmosphere, reviewed photography and material cues over flags, decorative skins or split-screen theme gimmicks.
   - Ensure the bilateral treatment still works with missing media, narrow screens, large text and reduced motion.
   - **Current production slice:** the converter result now uses one source/destination identity rail, country-theme tonal accents and managed destination media composition without flags or split-screen skins. Finland, Japan and France have sourced P01–P04 showcase selections with reviewed focal/derivative plans; runtime rendering still requires explicit managed-media approval/publication. Browser QA covers narrow/reflow states, forced colors and reduced motion.

8. **Favourite currencies — 67/100**
   - Allow users to save currencies independently of full source/destination pairs where this improves repeat conversion.
   - Keep this secondary to favourite places for the travel-first experience and avoid duplicating saved-pair controls.
   - **Current production slice:** shipped as a currency-only shortcut that stores no amount, country or FX snapshot. Signed-in users have owner-scoped `SavedCurrency` records with no-JavaScript save/remove/clear and canonical source/destination re-entry. Anonymous users can keep up to 24 browser-local currency shortcuts; sign-in never uploads them automatically, and an explicit import action moves only the confirmed codes into the account while preserving local copies if cleanup fails.

9. **Historical motion / animated history — 60/100**
   - Use restrained motion to explain currency transitions, timelines or Then & Now state changes.
   - Prefer informative timeline/map/date transitions over decorative re-enactments.
   - Respect reduced-motion preferences and never make animation necessary to understand the historical content.
   - **Current production slice:** shipped through the canonical Historical Series rather than a separate animation system. Chronological range anchors and Then & Now cards carry the meaning in static HTML; the existing Chart.js line visualization adds only a restrained 220 ms draw transition when motion is allowed. `prefers-reduced-motion: reduce` disables chart animation entirely. The same observations remain available through the textual summary, selected/minimum/maximum/last facts and accessible data table, while `noscript` keeps the non-visual path usable. Motion never changes rate/date/provider truth and is not required to understand the history.

Implementation order inside this queue can change when dependencies overlap. Prefer extending existing domain models, saved-state boundaries, historical flows and media/provenance systems over creating parallel feature-specific architecture.

### Second expansion wave from the broader product specification

The following additional user-facing capabilities also clear the current **60/100 usefulness + distinctiveness threshold**. They should follow or interleave with the queue above when dependencies make that more efficient.

11. **Budget interpretation — 91/100**
   - Help answer “Is this amount likely to be enough for this destination and duration?” using sourced local-price context and explicit assumptions.
   - Support duration and a small number of understandable spending profiles/categories without turning the product into a full itinerary planner.
   - Label outputs as estimates and keep deterministic calculations separate from AI-written explanation.
   - **Current status:** deterministic domain interpretation plus the user-facing progressive UX are implemented: signed conversion/scope handoff, duration, traveller count, explicit editable daily reference items, city/national scope preservation, provenance-bearing line estimates, neutral reference bands, fail-closed insufficient-data semantics and a no-JavaScript fallback. Real Payment Estimate now has a signed, capability-bounded handoff into Budget Interpretation: explicit fee/markup assumptions are re-applied server-side, the payment-adjusted planning amount is visibly separated from the trusted reference conversion, and the budget basis survives subsequent submits without client-side financial calculation. A successful reference-conversion or payment-adjusted interpretation can be explicitly saved to an authenticated account through the shared SavedScenario domain. Payment-adjusted saves preserve the deterministic planning amount and explicit fee assumptions while the raw initial FX observation remains immutable evidence; Trip Budget Remaining, returning-trip continuity and Offline Pack all resolve the same saved basis. Exact-pair reusable Payment Estimate fee profiles are shipped. Account-owned reusable Budget Interpretation presets are now also shipped: they store only duration/travelers/category-unit assumptions, preserve unsourced selected categories explicitly and rerun against the current signed planning context rather than replaying destination/FX/price snapshots.

12. **Saved scenarios — 89/100**
   - Evolve beyond pair-only bookmarks so a user can save a reusable travel-money scenario such as a trip budget or shopping calculation.
   - Design the scenario model so existing FavouritePair and RecentConversion data can coexist or migrate safely rather than creating duplicate persistence concepts.
   - Keep ownership, browser-local/account sync and privacy semantics explicit.
   - **Current status:** normalized account-owned SavedScenario persistence is implemented with typed trip/budget/shopping kinds, canonical destination city scope, normalized budget assumptions, optional validated travel dates and immutable initial/re-check FX observations. The first user-facing budget flow supports explicit account save, listing in Saved & recent, owner-scoped detail/reopen, converter return, deletion, explicit live reference-rate re-check and deterministic trip-timing readiness. Anonymous local scenarios and account/local sync remain future work. Shopping now has explicit account save/detail/reopen with normalized assumptions and immutable FX observations.

13. **Saved trip / budget detail — 85/100**
   - Give a saved travel-money scenario a focused detail page with current local value, typical costs, money tips, relevant conversion history and remaining budget where the user has entered spending.
   - During an active trip, surface simple spent / remaining / approximate-per-day values without becoming a general-purpose expense tracker.
   - Keep scope intentionally narrower than a full trip planner or expense-management product.
   - Reuse destination context, history and scenario data rather than duplicating them into a separate content system.
   - **Current slice:** authenticated budget scenarios now have a focused detail page showing destination, duration/travellers, optional saved travel dates, deterministic upcoming/active/ended readiness, normalized basket assumptions and immutable saved/latest FX observations, plus explicit reference-rate re-check, neutral since-saved comparison, converter return and delete actions. Trip Budget Remaining is shipped as a separate lightweight spend/remaining-budget slice. Current reviewed local-price/payment context can now be refreshed explicitly on the detail page without a live FX request or persistence: the latest stored FX output is used only as the purchase-example amount anchor, while empty/degraded context leaves stored observations and the remaining-budget baseline untouched. Automatic background context refresh remains future work.

14. **Rate changed since last visit — 84/100**
   - When a user reopens a saved pair/scenario, show how the current reference rate differs from the last relevant stored observation.
   - Preserve effective-date/provider semantics and avoid implying investment significance.
   - Treat the comparison as a return-usefulness feature, not as a trading signal.
   - **Current slice:** saved budget scenarios support an owner-scoped POST re-check against the latest available reference rate. Distinct observations append immutably; duplicate provider observations are deduplicated; the detail page compares the latest stored output/rate with the original saved observation using neutral more/less/unchanged language. Provider failure leaves existing scenario history untouched.

15. **Destination comparison — 83/100**
   - Let a user compare what the same source amount roughly means across two destinations.
   - Compare sourced everyday-value, payment-context and budget assumptions side by side while keeping currency/country identity distinct.
   - Avoid flattening country-wide estimates into false precision; city/scope differences must remain visible.
   - **Current production slice:** the deterministic comparison domain is exposed through a provider-free entry page and explicit POST orchestration. The user supplies one source amount/currency, two country/canonical-city destinations and one shared duration/traveller/reference-basket assumption set. Each side is quoted through the canonical converter/MoneyContext path and retains effective date/provider/stale semantics, city/national scope, price provenance and payment context. Partial coverage remains visible; no winner/ranking, direct cross-currency price ratio, PPP claim or generic cost-of-living index is produced. Explore and Saved continuity rows can hand one reviewed canonical destination into the left side of Compare without selecting or inferring the second destination; exact city scope is preserved where stored. Durable `SavedComparison` persists canonical inputs and explicit basket assumptions only: Reopen is provider-free, while Re-check explicitly returns through the canonical comparison POST path.

16. **Product modes: Quick / Travel / Budget / Shopping — 80/100**
   - Use one shared conversion/domain engine and expose progressively richer workflows rather than building four separate products.
   - Quick stays closest to the current converter; Travel adds destination money context; Budget adds duration/spending assumptions; Shopping adds purchase-cost inputs.
   - Do not force a mode choice before a user can perform the primary conversion.

17. **Shopping calculation — 76/100**
   - Support a foreign-currency purchase scenario with item price plus optional shipping and explicit user-supplied fees.
   - Separate deterministic arithmetic from uncertain duties/taxes/issuer costs and label unknowns clearly.
   - Save/reopen the calculation through the shared scenario model when that model exists.
   - **First production web slice:** `ShoppingAssumptions` composes item price, shipping and explicitly known purchase-currency fees; the canonical current conversion runs purchase currency → home currency for exactly that total; optional user-entered FX markup is applied transparently after the trusted reference cost. The provider-free entry page validates optional purchase-country scope before provider access, preserves submitted assumptions on provider failure, exposes provider/effective-date/stale semantics and labels duties, taxes and unentered issuer/merchant fees as unknown rather than estimating them. Historical/same-currency misuse and invalid numeric bounds fail closed. Account save/detail/reopen is now implemented through a signed Shopping handoff into the shared SavedScenario model. Exact item/shipping/known-fee/markup inputs are normalized separately from the immutable FX observation; reopen is provider-free and rate re-checks append evidence without rewriting the saved estimate.

18. **Rate alerts — 74/100**
   - Allow an opted-in user to watch a saved pair/scenario and receive a notification when a clearly defined rate-change condition is met.
   - Prefer scenario meaning over generic FX noise: explain what the movement changes for the user's saved trip amount when that is defensible.
   - Make thresholds, cadence and disable/delete controls explicit.
   - Keep alerts informational and avoid trading/investment framing.
   - **Current production slice:** SavedScenario rate alerts now require an explicit 0.1–25% threshold and cadence. The due generator probes the canonical current FX path without writing a new scenario observation, compares the transient rate/output against the immutable initial baseline and creates an owner-scoped in-app message only when the threshold is crossed. Stale/provider-failed probes fail closed. Local-calendar cadence, last-delivered state and a database dedupe key make repeated scheduler execution safe.

19. **Shareable conversion / travel-money cards — 68/100**
   - Create a compact share surface from trusted conversion and destination-context data.
   - Include effective-date/source context when a shared number could otherwise look current forever.
   - Keep social/OG presentation downstream of the canonical product data rather than introducing a second calculation path.
   - **Current production slice:** managed `SOCIAL_PREVIEW` media still feeds OG/Twitter image metadata on Explore, City Money Profile and Money & Culture. Canonical conversion results expose a signed public-by-link read-only page plus exportable 1200×630 SVG rendered from the already-computed immutable ConversionResult snapshot, preserving effective/requested date, fetched-at, provider, historical granularity and stale semantics without a second FX request. Saved scenarios now expose a separate explicit **Share safe snapshot** action built from the newest already-stored scenario observation. Its signed token contains only scenario kind, a non-sensitive destination/purchase label, input/output amounts, currencies, rate, effective/fetched time, provider attribution and stale state. It excludes account/scenario identifiers, private title, travel dates, duration/travellers, confirmed spend, Camera data and notification state. Opening the public HTML/SVG performs no account, database or FX/provider lookup and never refreshes the represented number. Copy/native-share behavior remains progressive enhancement.

20. **Personalized trip/scenario covers — 62/100**
   - Allow an optional decorative cover for a saved scenario when it adds delight without affecting factual meaning.
   - Prefer reviewed/sourced destination media first; if generated imagery is ever allowed, keep it explicitly synthetic and within the managed-media review boundary.
   - The feature must never block saving or reopening a scenario.

These scores are product-prioritization signals, not implementation guarantees. Before starting each item, validate the underlying data quality, legal/licensing implications, privacy impact and maintenance cost.

### Third expansion wave from the integrated product concept

The integrated product concept adds three non-duplicative user-facing capabilities that also clear the **60/100 usefulness + distinctiveness threshold**.

21. **Cultural-history portal — 87/100**
   - Provide one compact progressive-disclosure destination for cultural snapshot, currency story, previous currency, money etiquette, travel-money tip and a sourced memorable fact.
   - Treat this as an exploration surface, not a generic help dialog; the trigger must have an accessible name even if the visual design uses a compact icon.
   - Reuse reviewed story/provenance data and the existing currency-history domain rather than generating unsourced filler.
   - **Current production slice:** Money & Culture combines canonical currency-era chapters with reviewed historical moments, honest temporal precision, source publication/retrieval/review metadata and explicit causal-support semantics. Optional `STORY_CHAPTER` imagery is independently selected by chapter date under the same sourced historical-evidence rules as timeline media; duplicates are suppressed and missing media never blocks the story. Historical Series separately supports reviewed `COMPARISON_THEN`, `COMPARISON_NOW` and `HISTORICAL_TIMELINE` roles without implying that imagery explains FX movement.

22. **Pre-trip reminder / saved-scenario re-check — 82/100**
   - Let an opted-in user receive a reminder to re-open a saved trip/budget scenario near its planned travel date.
   - Refresh rate/local-value context on re-open and explain what changed under the same explicit assumptions.
   - Include destination/offline-pack freshness when it materially affects readiness for travel.
   - Keep reminders separate from speculative rate timing, easy to disable and privacy-conscious.
   - **Current production slice:** saved scenarios expose explicit notification configuration and an owner-scoped in-app inbox. Pre-trip reminders use only explicit saved travel dates. Context/offline freshness reminders run only near departure when the newest stored FX reference is stale or at least seven days old and ask the user to explicitly re-check context/replace any offline pack rather than silently refreshing it. Delivery generation is scheduler-friendly and repeat-safe through timezone-aware cadence, last-delivered evidence and a database dedupe key. Automatic background local-context refresh remains future work. The explicitly refreshed Saved Trip money guide now also surfaces short, date-filtered national-holiday and reviewed payment-readiness facts with evidence links. It reuses the already assembled current Money Context and never updates stored FX or claims to know venue opening hours.

### Enabling data/content foundation

Several ideas in the integrated concept are better treated as shared foundations rather than separate end-user features:

- **Structured country money profiles** for sourced typical-price anchors, cash/card/ATM/tipping/DCC context and explicit scope/observation metadata.
- **Country content packs** for cultural preview, currency fact, previous-currency context, local money behaviour, travel-money tip and buying-power anchors.
- **Country theme profiles** for restrained atmosphere, approved visual cues and prohibited clichés.

Build these as reusable, provenance-aware data/content systems that support multiple roadmap features instead of duplicating country-specific content inside individual views.

### Fourth expansion wave from the travel-money intelligence concept

The travel-money intelligence concept adds the following non-duplicative user-facing capabilities above the current **60/100 usefulness + distinctiveness threshold**.

24. **City-level money intelligence — 93/100**
   - Add city-scoped local-value and budget context where data quality supports it, because national averages are often too broad for practical travel decisions.
   - Keep city/national scope visible and never silently substitute one for the other.
   - Reuse the same provenance/freshness model as country-level typical prices.
   - **Foundation status:** canonical `City` identity exists; `TypicalPrice` has an additive canonical city reference with legacy-row backfill, the destination-context service can select an explicit city with national fallback for missing categories, and the budget domain preserves those city/national scopes. The city data-quality contract adds normalized category/unit semantics, published canonical-city/current-primary-currency/freshness/provenance validation, stable quality issue codes and DB-backed city/national observation identities. A read-only city coverage health report exposes per-city current currency, fresh/stale/fallback/provenance coverage and a maintenance-only 0–100 score using the same policy contract. Two reviewed dataset waves now give ten cities direct 4/4 fresh core coverage through the same canonical `TypicalPrice` store: Helsinki, Turku, Stockholm, Copenhagen, Oslo, Berlin, Tokyo, Singapore, Toronto and Auckland. The second wave adds three new current-primary currency relationships (SGD, CAD and NZD), reuses Tokyo's existing official Metro anchor instead of duplicating it, and keeps all city-level contextual rows separate from authoritative transit evidence. Across these ten cities the runtime can resolve 40 direct core anchors without national fallback; no affordability/value ranking is derived from them. Canonical city selection is exposed through Destination Mode and Destination Comparison, and Explore publishes city cards only with explicit city evidence. A dedicated provider-free City Money Profile is now shipped on top of the same canonical context: it requires direct city evidence, shows the current primary currency, reviewed price anchors, explicit national fallback, freshness/provenance and reviewed country payment guidance, and preserves city scope into Convert, Budget and Compare. The City Profile now also presents already-ingested current country-level inflation/price-level and published national public holidays when available, with original source/period and explicit national scope, without a provider request or city-level inference. The City Profile itself creates no separate financial-data or geography path: Explore uses the shared My Places contract, which is browser-local anonymously and owner-scoped when signed in. Account place records keep canonical country/city identity only and resolve current currency again at read time; the existing budget/scenario workflow keeps its separate scenario ownership. The city/national fallback trust audit is now executable: national-only evidence cannot manufacture a city profile/card, fallback scope stays visible, wrong-currency and stale rows fail closed, and cross-country city references are rejected both by the quality contract and defensively at the context query boundary.

25. **Camera mode for menu / receipt / price / ATM understanding — 90/100**
   - Let a user explicitly capture or upload a menu, receipt, shelf price or ATM screen and extract amount/currency/context for conversion.
   - Require user confirmation before financial interpretation when OCR/model extraction is uncertain.
   - When an active saved trip exists, optionally let the user add the confirmed expense amount to that trip so the lightweight remaining-budget view updates.
   - Treat screenshots and receipts as potentially sensitive; minimize retention and never infer hidden banking credentials.
   - **Current slice:** saved budget scenarios now have an opt-in Camera extraction/confirmation flow behind an explicit runtime flag. Accepted images are byte/pixel bounded, decoded/re-encoded in memory to strip metadata, sent to the configured Gemini multimodal adapter only after explicit upload, and never persisted by the application. The provider contract returns at most six amount/currency/kind/confidence candidates and intentionally excludes receipt/merchant/account text. Explicit currency mismatches are blocked; users can correct the amount; confirmation yields a short-lived scenario-scoped signed token. A separate explicit **Add to trip budget** POST now consumes that token, verifies scenario/currency scope and persists only the confirmed amount through the existing idempotent spend contract with source=`camera`; replaying the same confirmation cannot double-count spend, while separate confirmations remain distinct.

26. **Explore / discovery mode — 88/100**
   - Offer a discovery surface for sourced money-context collections such as same-amount destination comparisons, card/cash patterns, currency stories and regional exploration.
   - Use only comparable, scoped data for rankings or “goes further” claims.
   - Keep Explore downstream of the converter rather than turning the product into a generic travel-content portal.
   - **Current production slice:** a provider-free Explore page discovers only reviewed current destination scopes through the existing `DestinationContext` provenance/freshness rules. Country and city scopes keep their original evidence semantics, and all five deterministic collections now render in the frontend with inspectable provenance: city money profiles, published currency stories, reviewed cash/card behaviour, current shared-currency country groups and recently reviewed destinations. A premium no-JS region → country → city directory reuses canonical `Country.region/subregion` and `City.country` identities; unknown geography remains visible in an explicit final fallback group. Destination composition is reused across collections and navigation rather than recomputed, optional enrichment failures degrade locally, and country/city actions hand scope back to canonical product flows. Same Amount Across Destinations is now a separate descriptive Explore decision surface over canonical current conversions and Money Context, with independent evidence/provider semantics and no winner/PPP/affordability ranking. Reviewed country/city rows and destination-oriented collections can also seed exactly one canonical side of Destination Comparison; Explore never silently chooses the second side. Canonical country/city rows can be saved through browser-local My Places anonymously or owner-scoped SavedPlace when signed in and reopened through the Saved page without introducing a second geography or price model. Browser-local → account migration remains explicit rather than sign-in-triggered. Explore itself performs no live FX call. Its optional contextual AI surface now accepts only a reviewed canonical destination plus one server-approved intent, rebuilds trusted current destination context server-side, and sends only a bounded structured fact packet to the existing validated AI delivery stack. AI output cannot create rates, prices, payment guidance, rankings, affordability or purchasing-power truth; provider failure falls back to the same grounded structured result shape.

27. **Contextual AI quick prompts — 87/100**
   - Offer a few relevant next questions derived from the current conversion/scenario instead of presenting an empty chatbot.
   - Examples can cover budget fit, cash need, payment warnings, rate explanation and destination comparison.
   - Prompts must resolve through bounded trusted context and remain optional.
   - **Current production slice:** current/historical conversion results expose only server-approved questions supported by the signed conversion snapshot. Current conversions offer reference-rate meaning and bank/card-difference questions; stale current results may additionally explain the cached-reference state; historical results replace payment guidance with an observation-date question. The posted `prompt_id` is validated server-side before any AI service is built, arbitrary prompt text is ignored, the selected intent is part of the grounded packet/cache identity, and generated output must cite the intent's required fact IDs. Explore uses a separate trusted destination-context packet with server-approved overview, cash/card and price-evidence questions. Budget Interpretation and Destination Comparison are also shipped behind capability-scoped signed fact packets built only after deterministic calculation; those explanation endpoints cannot recompute FX/prices, fill missing coverage, rank destinations or become financial truth.

28. **Structured AI insight panel — 86/100**
   - Present AI-assisted answers in a predictable structure such as short answer, key factors, one caution and next step.
   - Keep deterministic/sourced facts visually distinguishable from generated explanation.
   - A failed AI response must not remove or invalidate the conversion/context result.
   - **Current production slice:** runtime explanations now use one schema-versioned structured contract with `short_answer`, `key_factors`, `watch_out_for` and `next_step`. Every section carries supporting fact IDs, the validator rejects unknown facts/extra fields/unsupported numbers/dates/currencies and selected quick-prompt intents still require their declared grounding. Deterministic fallback uses the same structured result shape, so provider failure does not create a second UI/data contract. Historical panels also carry an explicit grounded boundary that historical FX is not historical purchasing power.
   - **Reliability slice:** prompt requests expose accessible loading/busy state, only the active prompt is disabled, a newer prompt replaces an older in-flight request, swapped answer/error content receives focus, timeout fallback remains visible with an explicit retry path, transport errors are announced without removing the conversion, and the full interaction is exercised in browser CI through a test-only deterministic drafter that is rejected outside `APP_ENV=test`.

29. **Smart result summary — 84/100**
   - After a successful conversion, optionally show one concise grounded sentence describing the most useful implication of the result.
   - Prefer deterministic templating when it can communicate the point reliably; use AI only when it adds material explanatory value.
   - Never turn the summary into an unsupported recommendation or investment-style signal.
   - **Current production slice:** every successful converter result now receives one deterministic at-a-glance summary. Trust semantics win before enrichment: historical results preserve the historical-FX vs purchasing-power boundary, stale results identify the cached reference, and same-currency results stay exact/provider-free. Current non-stale results may use only the first reviewed Money Context price anchor that already passed provenance/freshness validation; otherwise they fall back to reviewed payment guidance or a neutral reference-rate limitation. Unknown/zero purchase-equivalent states fail closed rather than breaking the conversion. Current, fresh, context-backed results additionally reveal up to three complementary sourced fact cards (reviewed card-terminal guidance, published national holidays and a different local-price anchor) with links to the canonical Money Context Lens. Cards are omitted for stale, historical, exact-identity or mismatched contexts, and never repeat the primary summary's payment/price fact. No AI, ranking, cheap/expensive label or inferred affordability is used.

30. **Offline destination packs — 82/100**
   - For future mobile/offline use, allow selected destination money context to remain useful with limited connectivity.
   - Define freshness/expiry for rates versus slower-moving payment/cultural content; never present stale FX as current.
   - A last-known FX observation may be useful offline only when its provider/effective timestamp and stale/offline status are explicit; it must never masquerade as a live rate.
   - Keep offline scope small enough to remain maintainable and privacy-conscious.
   - **Current production slice:** an account-owned saved budget scenario can download a versioned self-contained HTML pack **and** explicitly save a read-only installed-app snapshot on the current browser/device. Both reuse the same provider-free snapshot contract: newest stored FX evidence, immutable-baseline Trip Budget Remaining, reviewed destination context and explicit generated/as-of semantics. Ordinary navigation HTML remains network-first and is never automatically cached. The private PWA cache is written only after **Save trip for offline**, routes only the matching saved-scenario URL while offline, and is labelled stored/not-live. A deterministic revision covering scenario assumptions, observations and confirmed spend marks a device copy out of date after meaningful saved-state changes; refresh/replacement and removal are explicit. A conservative age reminder is separate from financial freshness truth. Native-mobile storage remains future work.

31. **Lightweight personalization — 79/100**
   - Allow opt-in preferences such as home currency, preferred language, travel style or answer-detail level to reduce repetitive setup.
   - Reuse stable user-selected defaults when creating the next trip so returning users do not repeat unchanged setup.
   - Use saved/recent behaviour cautiously; do not silently build a sensitive travel/financial profile or copy destination-specific spending history into a new trip.
   - Personalization should improve defaults and explanations without changing deterministic financial truth.
   - **Current production slice:** signed-in users can set or clear one active home currency in Account. Fresh Converter, Destination Mode and Destination Comparison reuse it only as a starting source-currency default; explicit URL/reopen/submitted state takes precedence. Users can also explicitly choose optional AI explanation language (English/Finnish/Ukrainian), answer-detail level and a bounded travel emphasis (balanced/budget-conscious/comfort-first). These preferences are injected only into server-owned explanation packet metadata/instructions: they cannot change FX, prices, budget assumptions, deterministic comparison results or fact allow-lists. Anonymous users keep safe defaults, database lookup failure degrades to defaults, and no location/history/trip inference is used. Reusable Budget Interpretation assumption presets remain separate from the account-default model.

32. **Actionable history shortcuts — 74/100**
   - Let a past conversion reopen into useful follow-up actions such as repeat, compare, save as scenario/trip or open relevant context.
   - Preserve original requested/effective dates and provider semantics when historical records are reused.
   - Avoid turning history into a noisy action dashboard.
   - **Current production slice:** Saved & recent now acts as a restrained continuity hub across account-owned and browser-local state. Saved scenarios reopen through their canonical detail flow and may seed exactly one canonical Destination Comparison side from their stored country/city scope. Account/browser favourites restore their pair without storing an amount, may seed the stored destination country into Compare, and keep Reverse pair as a tertiary action. Account/browser recent conversions preserve amount plus historical requested/effective-date semantics for Repeat, may seed only the recorded destination country into Compare, and keep Swap separate. A separate Plan again action now uses the recorded starting amount (only with a still-active source currency) and current destination identity to seed Destination Mode; it never transfers the old FX rate/output or historical dates. Browser-local My Places expose a parallel destination-only Plan shortcut, preserving reviewed country/city identity so Convert and Compare retain exact city scope when available. Comparison shortcuts never infer the second destination and introduce no saved-comparison datastore. Empty Saved states provide one bounded next action back into canonical Explore, Convert or Destination Mode flows.

33. **Voice interaction — 68/100**
   - Allow an explicit voice query for travel-money questions when hands-free interaction materially helps, especially on mobile during travel.
   - Route recognized content through the same structured budget/conversion/context services as text.
   - Keep voice optional, privacy-conscious and non-essential to any core workflow.

Items already represented elsewhere—destination comparison, trip dashboard/detail, saved trips, alerts, share cards and payment profiles—remain part of their existing roadmap entries rather than being duplicated here.

### Sixth expansion wave: retention and trip continuity

The retention strategy adds three non-duplicative capabilities that strengthen the natural travel lifecycle instead of manufacturing generic daily engagement.

35. **Trip Budget Remaining — 92/100**
   - Let an active saved trip keep a deliberately simple starting budget, confirmed spend, remaining amount and approximate remaining-per-day value.
   - Accept manual additions and, later, confirmed camera-extracted expenses; never auto-bookkeep ambiguous OCR results.
   - Keep this narrower than expense management: no accounting categories, reconciliation or ledger complexity unless later evidence justifies expansion.
   - **Current slice:** account-owned saved budget scenarios can record/remove minimal immutable confirmed-spend entries in the destination currency. Replayed web submissions are idempotent, add/remove operations are transaction-safe, scenario creation establishes the initial FX baseline, and the database prevents a second initial observation for the same scenario. Remaining/over-reference arithmetic is anchored to that immutable initial saved FX output, not later re-check rates; per-day meaning uses explicit saved duration/date semantics and fails closed when the remaining travel window cannot be known. Merchant/receipt/free-text purchase data is not stored. Camera-confirmed amounts now enter this same spend contract only after a separate explicit signed-token handoff and are labelled with the camera confirmation source.

36. **Returning-user trip home — 89/100**
   - For users with an upcoming trip, replace repetitive setup with a compact continuity surface showing destination, dates, budget, rate change, context freshness and the next useful action.
   - Keep first-time/anonymous entry converter-first; only personalize the home surface when the user has saved relevant state.
   - Prefer quick actions such as Scan price, Check budget, Money tips and Open trip over a dense dashboard.
   - **Current production slice:** a clean authenticated converter home now promotes one account-owned active/started/upcoming saved trip without performing a live FX request. Active travel wins, then started-without-end, then the nearest upcoming trip. The surface reuses stored trusted observations, immutable-baseline Trip Budget Remaining, reviewed city/country context freshness and explicit Camera/offline/detail actions. Anonymous/new users, explicit conversion deep links, loaded pairs, ended trips and unscheduled scenarios remain converter-first.

37. **Mobile home-screen quick actions / widget — 80/100**
   - When native mobile is active, expose a minimal glanceable surface for an active trip, such as current reference conversion or remaining trip budget.
   - Provide fast entry to the highest-value point-of-use actions, especially Scan and Convert.
   - Never show a stale/offline FX observation as current; include freshness/state when a number could otherwise be misread.

### Retention-first sequencing

Retention work should follow the dependency order of the product, not engagement-fashion conventions.

**P0 foundation sequence:** SavedScenario / Trip → Budget interpretation → Rate changed since saved → Pre-trip re-check → Destination Mode. First production slices now exist through Destination Mode.

**P1 dependency sequence:** Trip Budget Remaining foundation ✅ → Camera extraction/confirmation ✅ → Camera-confirmed spend handoff ✅ → Offline destination pack ✅ → PWA install/offline shell ✅ → explicit active-trip device snapshot + lifecycle ✅ → Returning-user trip home ✅. Camera confirmation and persistence remain separate explicit actions, and every offline surface reuses stored-FX/freshness semantics without introducing a second calculation path.

**P2:** Scenario-based notifications → mobile quick actions/widget → saved-comparison continuity → broader Explore. The first destination-comparison web slice and the first provider-free Explore slice are already shipped.

The target is not maximum DAU. The target is strong **saved-trip reopen**, **uses per active travel day**, and **return for the next trip**.

### Strategic product foundation: Money Context Engine

The first consolidation is now shipped as a shared application contract around trusted conversion output plus optional current destination context. It explicitly preserves conversion truth, fail-open enrichment semantics and available/empty/not-applicable/degraded context states.

The next work is depth, not another parallel context layer: broaden city-scoped datasets and dedicated city UX, deepen Explore and contextual AI consumers, and eventually add mobile consumers on top of the same contract. Budget, saved-trip, comparison, Camera and offline/returning-home web consumers already reuse this shared meaning.

Prioritize comparability, freshness, provenance and clear uncertainty over adding many shallow utility widgets.

## Stable external/mobile API

**Current production slice:** a versioned public read-only `/api/v1/` foundation now exposes capability discovery, active reference metadata and canonical current/historical conversion plus Money Context. The conversion endpoint validates through the existing `CurrentConversionForm` and executes through `run_converter_submission`; it does not introduce a second FX, rounding, historical or destination-context path. Financial decimals are JSON strings, rate/provider/effective/fetched/stale semantics remain explicit, unknown request fields fail closed and provider exceptions are mapped to stable safe machine codes. v1 intentionally exposes no account/scenario/Camera/notification mutations and enables no wildcard browser CORS. A later authenticated account API must define a separate token/scoping/revocation boundary before native saved-state sync is exposed.

## Later candidate: native mobile

Mobile is a strategically important point-of-use surface for this product: users may need money context at checkout, in cafés/shops, on public transport or before using an ATM. It should become an active product priority once the Money Context Engine, API contract and offline/staleness semantics are stable enough to reuse safely.

A native client should reuse backend/domain meaning rather than duplicate web business rules. Point-of-use value should include quick conversion, Camera, active-trip budget continuity, offline destination context and—when platform support is appropriate—a small home-screen widget/quick-action surface.

Choose the current stable mobile stack when implementation starts; do not rewrite the web architecture merely to anticipate mobile.

## Later candidate: deeper trip/budget workflows

After the scoped budget interpretation and saved-scenario work above has real usage evidence, consider deeper trip/budget capabilities. Keep this boundary narrower than itinerary planning or a general-purpose expense tracker unless user evidence justifies expanding the product.

## Research: historical purchasing power

Historical FX and historical purchasing power are different questions. Shipping purchasing-power claims requires defensible datasets, methodology, provenance and uncertainty communication.

## Production hardening

PostgreSQL backup/clean-restore recovery and runtime observability now have executable CI evidence.

As public usage grows, continue with deployment-specific backup scheduling/retention and measured RPO/RTO, provider-incident drills, and measured object-storage versioning/restore evidence. Production configuration now requires durable S3-compatible managed-media storage rather than an ephemeral application filesystem. Deterministic frontend/query performance budgets now have a measured CI baseline; real-user timing thresholds remain a future evidence task. Security headers remain part of the tested deployment baseline.

## How to add roadmap work

Add work when it has a user outcome, enough evidence to justify it and a rough dependency/risk picture.

Use issues/PRs for implementation detail rather than creating another parallel roadmap document.
