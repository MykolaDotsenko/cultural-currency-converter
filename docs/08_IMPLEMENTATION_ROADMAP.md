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

## Later candidate: stable external/mobile API

A versioned API is useful when a native client or external consumer becomes active.

Before implementation, re-evaluate framework/schema/authentication/offline choices against the then-current product.

## Later candidate: native mobile

A native client should reuse backend/domain meaning rather than duplicate web business rules.

Choose the current stable mobile stack when implementation starts.

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
