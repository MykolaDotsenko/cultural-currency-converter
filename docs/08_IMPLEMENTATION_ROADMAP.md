# Roadmap

This roadmap is active direction, not a frozen PR sequence.

Re-evaluate priorities as product value, code quality and deployment needs become clearer.

## Current baseline

The web product already includes:

- current and historical FX conversion;
- country/currency temporal modelling;
- historical trends and Then & Now;
- destination payment/everyday-value context;
- deterministic culture/story content;
- managed raster media with provenance/review;
- optional AI explanation with deterministic fallback;
- browser-local favourites/recent conversions;
- account authentication and durable favourites;
- separately opt-in account recent history;
- browser accessibility/reflow quality gates.

The old release-owned cartoon SVG media pack has been removed.

## Now: premium visual pass

Raise the existing web product to a more expensive, editorial visual standard.

Priority outcomes:

- use the Finland curated-photography vertical slice as the reference implementation for source review, managed ingestion, responsive derivatives, attribution and destination-context rendering;
- curate realistic contemporary country photography for additional destinations;
- expand reviewed country-media coverage now that hero, everyday-value, payment-culture and local-detail roles are wired into destination context;
- keep the converter clean when photography is unavailable;
- validate focal-point crops across responsive ratios and keep tonal treatment consistent across real country photography;
- expand authentic archival/heritage coverage now that Then & Now supports currency/date-scoped sourced historical media;
- remove remaining visual patterns that feel demo-like or decorative;
- simplify UX where controls/content are duplicated;
- continue auditing empty/degraded states beyond the destination-context fallback already made trust-explicit;
- profile product performance with real photographic media;
- improve portfolio/demo clarity.

Do not add images simply to increase visual density.

## Next: high-value product expansion

After the premium visual pass, implement the strongest remaining concepts from the original project vision. This queue contains only features that currently score **60/100 or higher** for combined user usefulness and product distinctiveness. The scores are planning aids, not permanent requirements; re-evaluate them if user evidence or implementation cost changes materially.

1. **Bilateral cultural experience — 91/100**
   - Keep source and destination culturally legible at the same time, not only financially legible.
   - Let both sides contribute useful local context such as place identity, everyday-value cues and destination atmosphere.
   - Preserve one coherent premium interface rather than turning the page into two unrelated themes.

2. **Currency story / previous-currency exploration — 88/100**
   - Add a clear progressive-disclosure entry point from a selected country/currency into its currency history.
   - Reuse the existing temporal country/currency model, archived currencies, historical FX, Then & Now and provenance rules.
   - When a country changed currency, explain the transition and expose relevant historical context without implying historical purchasing power.

3. **Travel-money companion layer — 88/100**
   - Expand destination context around practical money use rather than becoming a generic tourism guide.
   - Prioritize what an amount roughly means locally, payment habits, cash/card/ATM guidance, tipping/customs and repeat-trip usefulness.
   - Keep claims sourced, scoped and current; optional enrichment must remain non-blocking for conversion.

4. **Country ↔ currency smart filtering — 82/100**
   - Make the selector behaviour explicit: choosing a currency should narrow or explain relevant countries, and choosing a country should narrow or explain currencies valid for that country/date.
   - Preserve currency-only conversion when country context is unknown or unnecessary.
   - Respect shared currencies, archived currencies and temporal CountryCurrency relationships instead of hard-coding current-only mappings.

5. **Historical guide / currency timeline — 80/100**
   - Build a deeper historical exploration layer from the existing historical FX and Then & Now foundations.
   - Prefer concise timelines, currency-era transitions, sourced archival media and provenance over encyclopedia-style long-form content.
   - Keep historical FX separate from historical purchasing-power claims.

6. **Favourite countries / My Places — 76/100**
   - Let users save countries/places independently of a specific conversion pair.
   - Use saved places as shortcuts into common source/destination flows and destination money context.
   - Define browser-local versus account-owned persistence and migration/sync behaviour before shipping.

7. **Subtle bilateral visual styling — 74/100**
   - Give source and destination distinct but restrained visual identity inside the same Quiet Atlas Premium system.
   - Prefer typography, tonal atmosphere, reviewed photography and material cues over flags, decorative skins or split-screen theme gimmicks.
   - Ensure the bilateral treatment still works with missing media, narrow screens, large text and reduced motion.

8. **Favourite currencies — 67/100**
   - Allow users to save currencies independently of full source/destination pairs where this improves repeat conversion.
   - Keep this secondary to favourite places for the travel-first experience and avoid duplicating saved-pair controls.

9. **Historical motion / animated history — 60/100**
   - Use restrained motion to explain currency transitions, timelines or Then & Now state changes.
   - Prefer informative timeline/map/date transitions over decorative re-enactments.
   - Respect reduced-motion preferences and never make animation necessary to understand the historical content.

Implementation order inside this queue can change when dependencies overlap. Prefer extending existing domain models, saved-state boundaries, historical flows and media/provenance systems over creating parallel feature-specific architecture.

### Second expansion wave from the broader product specification

The following additional user-facing capabilities also clear the current **60/100 usefulness + distinctiveness threshold**. They should follow or interleave with the queue above when dependencies make that more efficient.

10. **Real Payment Estimate — 94/100**
   - Explain the gap between a reference market rate and what a user may actually experience when paying by card or withdrawing cash.
   - Model only defensible inputs/ranges such as user-supplied bank/card markup, known fixed fees or clearly labelled scenario assumptions.
   - Optionally allow a signed-in user to save explicit fee assumptions/profile defaults for reuse, with clear ownership/edit/delete controls; never infer issuer fees from unrelated behaviour.
   - Never present guessed bank, ATM, DCC or merchant fees as known facts; preserve the existing trust/provenance boundary.

11. **Budget interpretation — 91/100**
   - Help answer “Is this amount likely to be enough for this destination and duration?” using sourced local-price context and explicit assumptions.
   - Support duration and a small number of understandable spending profiles/categories without turning the product into a full itinerary planner.
   - Label outputs as estimates and keep deterministic calculations separate from AI-written explanation.

12. **Saved scenarios — 89/100**
   - Evolve beyond pair-only bookmarks so a user can save a reusable travel-money scenario such as a pair, trip budget or shopping calculation.
   - Design the scenario model so existing FavouritePair and RecentConversion data can coexist or migrate safely rather than creating duplicate persistence concepts.
   - Keep ownership, browser-local/account sync and privacy semantics explicit.

13. **Saved trip / budget detail — 85/100**
   - Give a saved travel-money scenario a focused detail page with current local value, typical costs, money tips, relevant conversion history and remaining budget where the user has entered spending.
   - Keep scope intentionally narrower than a full trip planner or expense-management product.
   - Reuse destination context, history and scenario data rather than duplicating them into a separate content system.

14. **Rate changed since last visit — 84/100**
   - When a user reopens a saved pair/scenario, show how the current reference rate differs from the last relevant stored observation.
   - Preserve effective-date/provider semantics and avoid implying investment significance.
   - Treat the comparison as a return-usefulness feature, not as a trading signal.

15. **Destination comparison — 83/100**
   - Let a user compare what the same source amount roughly means across two destinations.
   - Compare sourced everyday-value, payment-context and budget assumptions side by side while keeping currency/country identity distinct.
   - Avoid flattening country-wide estimates into false precision; city/scope differences must remain visible.

16. **Product modes: Quick / Travel / Budget / Shopping — 80/100**
   - Use one shared conversion/domain engine and expose progressively richer workflows rather than building four separate products.
   - Quick stays closest to the current converter; Travel adds destination money context; Budget adds duration/spending assumptions; Shopping adds purchase-cost inputs.
   - Do not force a mode choice before a user can perform the primary conversion.

17. **Shopping calculation — 76/100**
   - Support a foreign-currency purchase scenario with item price plus optional shipping and explicit user-supplied fees.
   - Separate deterministic arithmetic from uncertain duties/taxes/issuer costs and label unknowns clearly.
   - Save/reopen the calculation through the shared scenario model when that model exists.

18. **Rate alerts — 74/100**
   - Allow an opted-in user to watch a saved pair/scenario and receive a notification when a clearly defined rate-change condition is met.
   - Make thresholds, cadence and disable/delete controls explicit.
   - Keep alerts informational and avoid trading/investment framing.

19. **Shareable conversion / travel-money cards — 68/100**
   - Create a compact share surface from trusted conversion and destination-context data.
   - Include effective-date/source context when a shared number could otherwise look current forever.
   - Keep social/OG presentation downstream of the canonical product data rather than introducing a second calculation path.

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

22. **Pre-trip reminder / saved-scenario re-check — 82/100**
   - Let an opted-in user receive a reminder to re-open a saved trip/budget scenario near its planned travel date.
   - Refresh rate/local-value context on re-open and explain what changed under the same explicit assumptions.
   - Keep reminders separate from speculative rate timing, easy to disable and privacy-conscious.

23. **Historical quick ranges and anchor values — 78/100**
   - Add approachable historical range controls such as 1Y / 5Y / 10Y where provider coverage supports them.
   - Pair the chart with a small number of actual anchor observations and a grounded human-readable summary.
   - Preserve requested/effective-date semantics and avoid trading-style indicators or unsupported continuity.

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

25. **Camera mode for menu / receipt / price / ATM understanding — 90/100**
   - Let a user explicitly capture or upload a menu, receipt, shelf price or ATM screen and extract amount/currency/context for conversion.
   - Require user confirmation before financial interpretation when OCR/model extraction is uncertain.
   - Treat screenshots and receipts as potentially sensitive; minimize retention and never infer hidden banking credentials.

26. **Explore / discovery mode — 88/100**
   - Offer a discovery surface for sourced money-context collections such as same-amount destination comparisons, card/cash patterns, currency stories and regional exploration.
   - Use only comparable, scoped data for rankings or “goes further” claims.
   - Keep Explore downstream of the converter rather than turning the product into a generic travel-content portal.

27. **Contextual AI quick prompts — 87/100**
   - Offer a few relevant next questions derived from the current conversion/scenario instead of presenting an empty chatbot.
   - Examples can cover budget fit, cash need, payment warnings, rate explanation and destination comparison.
   - Prompts must resolve through bounded trusted context and remain optional.

28. **Structured AI insight panel — 86/100**
   - Present AI-assisted answers in a predictable structure such as short answer, key factors, one caution and next step.
   - Keep deterministic/sourced facts visually distinguishable from generated explanation.
   - A failed AI response must not remove or invalidate the conversion/context result.

29. **Smart result summary — 84/100**
   - After a successful conversion, optionally show one concise grounded sentence describing the most useful implication of the result.
   - Prefer deterministic templating when it can communicate the point reliably; use AI only when it adds material explanatory value.
   - Never turn the summary into an unsupported recommendation or investment-style signal.

30. **Offline destination packs — 82/100**
   - For future mobile/offline use, allow selected destination money context to remain useful with limited connectivity.
   - Define freshness/expiry for rates versus slower-moving payment/cultural content; never present stale FX as current.
   - A last-known FX observation may be useful offline only when its provider/effective timestamp and stale/offline status are explicit; it must never masquerade as a live rate.
   - Keep offline scope small enough to remain maintainable and privacy-conscious.

31. **Lightweight personalization — 79/100**
   - Allow opt-in preferences such as home currency, preferred language, travel style or answer-detail level to reduce repetitive setup.
   - Use saved/recent behaviour cautiously; do not silently build a sensitive travel/financial profile.
   - Personalization should improve defaults and explanations without changing deterministic financial truth.

32. **Actionable history shortcuts — 74/100**
   - Let a past conversion reopen into useful follow-up actions such as repeat, compare, save as scenario/trip or open relevant context.
   - Preserve original requested/effective dates and provider semantics when historical records are reused.
   - Avoid turning history into a noisy action dashboard.

33. **Voice interaction — 68/100**
   - Allow an explicit voice query for travel-money questions when hands-free interaction materially helps, especially on mobile during travel.
   - Route recognized content through the same structured budget/conversion/context services as text.
   - Keep voice optional, privacy-conscious and non-essential to any core workflow.

Items already represented elsewhere—destination comparison, trip dashboard/detail, saved trips, alerts, share cards and payment profiles—remain part of their existing roadmap entries rather than being duplicated here.

### Fifth expansion wave from the market assessment

The market assessment adds one genuinely new user-facing capability above the **60/100 usefulness + distinctiveness threshold**; the other strongest recommendations reinforce existing roadmap items rather than creating duplicates.

34. **Destination mode — 91/100**
   - Let the user start with “I’m in / I’m going to” a country or city and receive the relevant local currency plus scoped money context without first constructing a currency pair.
   - Manual destination selection is the baseline; device-location assistance, if ever added, must be optional and privacy-preserving.
   - Reuse country/currency temporal logic, city-level context, payment guidance, My Places and saved-trip flows rather than introducing a parallel destination data model.

### Strategic product foundation: Money Context Engine

Treat the existing everyday-value capability as a reusable product engine, not merely one post-conversion card.

The engine should serve converter, destination comparison, budget interpretation, trip/scenario detail, camera input and future mobile/offline experiences from the same scoped/provenance-aware context model.

Prioritize depth, comparability, freshness and clear uncertainty over adding many shallow utility widgets.

## Later candidate: stable external/mobile API

A versioned API is useful when a native client or external consumer becomes active.

Before implementation, re-evaluate framework/schema/authentication/offline choices against the then-current product.

## Later candidate: native mobile

Mobile is a strategically important point-of-use surface for this product: users may need money context at checkout, in cafés/shops, on public transport or before using an ATM. It should become an active product priority once the Money Context Engine, API contract and offline/staleness semantics are stable enough to reuse safely.

A native client should reuse backend/domain meaning rather than duplicate web business rules.

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
