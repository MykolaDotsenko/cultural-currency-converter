# Product

## Product statement

Cultural Currency Converter helps a traveller answer three connected questions:

1. **How much is my money worth there?**
2. **What does that amount roughly mean locally?**
3. **What should I know about money and payment culture in that destination?**

The conversion is the primary task. Context and culture should make the conversion more useful, not turn the product into an encyclopedia.

## Product identity and decision model

Cultural Currency Converter is best understood as a **country-aware travel-money decision assistant**: deterministic financial meaning at the core, practical local context around it, and cultural discovery as an optional layer.

### Category framing

Useful category language is **travel-money intelligence** or **destination money companion**. These phrases describe the product's broader role without changing the core trust boundary: the product helps users understand and use money in another country; it does not execute transfers, guarantee payment outcomes or provide regulated financial advice.

The long-term category ambition is a travel-money intelligence product that can support the user before and during a trip through conversion, local-value context, payment guidance, comparison, saved scenarios and optional AI-assisted explanation.

The working product formula is:

**Rate + Real Cost + Local Buying Power + Local Money Behavior + Cultural Context**

### Money Context Engine

The defensible product layer is not the exchange-rate calculation itself. It is the **Money Context Engine** that turns a trusted amount into practical meaning for a specific place.

Its core question is:

**What does this money mean here?**

The engine should combine, when defensible:

- reference FX and effective-date/source semantics;
- sourced everyday-value anchors;
- city/country scope;
- payment behaviour and relevant warnings;
- explicit fee assumptions for real-payment estimates;
- historical/cultural context;
- confidence, freshness and provenance.

“What this buys” should therefore be treated as a first-class product capability rather than decorative post-conversion content. The interface can stay simple, but the underlying context model should be reusable by converter, comparison, budget, trip, camera and mobile/offline flows.

The current implementation establishes the first shared application contract for this engine: a trusted conversion is composed with optional current destination context and an explicit availability state. Known destination-enrichment/data failures degrade locally and do not invalidate the conversion. Historical conversions and currency-only conversions remain explicit non-applicable cases for current destination context.

The first budget slice now extends this contract end to end: explicit duration, traveller count and editable daily category-unit assumptions can be compared with sourced city/national price anchors through a progressive web surface. Missing categories produce an insufficient-data result rather than a guessed affordability label. The current UX deliberately uses a visible reference basket rather than opaque “travel style” presets; richer presets and saved-trip workflows remain future work.

Saved-scenario persistence now has a normalized domain foundation for account-owned trip/budget/shopping scenarios. User-entered planning assumptions are stored separately from immutable trusted FX observations, so re-check flows can compare against an original baseline without treating stale local-price context as durable truth. The first user-facing account workflow is defined for validated budget interpretations: a signed-in user can save the trusted conversion, destination scope, explicit daily basket assumptions and optional travel dates; reopen them from Saved & recent; explicitly re-check the latest reference rate without overwriting the original baseline; inspect a neutral since-saved comparison; and delete the scenario. Saved travel dates drive deterministic upcoming/active/ended readiness states only; they do not create reminders, infer an itinerary or trigger background refresh. Anonymous/local saved scenarios, opt-in reminder delivery and broader trip-detail context remain future work.

Destination-first planning now has a first production slice. A user can begin with an explicit country or reviewed canonical city plus a source amount/currency; the product resolves the destination's current primary currency and redirects into the same canonical converter. City scope travels through the Money Context Engine when selected, while rate/provider/date semantics remain owned by the converter. Destination mode does not request an FX rate on its own and does not use device location.

The first Trip Budget Remaining slice extends saved budget scenarios into point-of-use planning. Confirmed spend is explicitly entered in the destination currency and subtracted from the immutable original saved FX output, so later rate re-checks never move the user's spending baseline. The surface can derive a remaining-per-day reference only from explicit saved duration/date information; it stops inferring a daily figure when a trip has started without an end date or has ended. Spend persistence is intentionally minimal—amount, confirmation source and timestamp only—and is not a bank balance, receipt archive or general expense ledger.

Destination comparison now has a first user-facing production slice. One explicit source amount/currency can be compared across two current country/canonical-city scopes using the same duration, traveller count and visible daily reference-basket assumptions. Each side retains its own trusted ConversionResult, effective date/provider/stale state, city/national price scope, provenance and payment context. Partial coverage remains visible, and the product deliberately produces no winner, direct cross-currency price ratio, universal cost-of-living index or purchasing-power claim.

Future trip, camera and mobile/offline work should extend the same contract rather than create parallel calculations or duplicate destination-context semantics.

The product should not treat generic cash/card tips or basic FX conversion as its moat; those utilities are increasingly commoditized. Differentiation comes from trustworthy, scoped money meaning plus cultural/historical context and useful return flows.

- **Rate** — a trustworthy reference FX observation with source/effective-date semantics.
- **Real Cost** — a clearly labelled estimate of card/ATM/exchange outcomes only when inputs or assumptions are defensible.
- **Local Buying Power** — sourced examples that translate an amount into everyday meaning.
- **Local Money Behavior** — practical cash/card/ATM/tipping/DCC context.
- **Cultural Context** — concise historical and cultural meaning that enriches, rather than blocks, the financial task.

### Mission

**To make currency conversion more useful, human, and culturally meaningful.**

### Vision

Turn currency conversion from a mechanical calculation into **understanding of money in place**.

### Product philosophy

- **Utility first. Cultural soul always.**
- **Practical first. Human always. Cultural in small doses.**
- **Two countries. Two worlds. One conversion experience.**

The product should preserve the original **“Bridging cultures through currency conversion”** idea without allowing cultural decoration to overpower trust, speed or practical usefulness.

## Messaging and tagline hierarchy

The product should keep one recognizable brand voice while adapting the message to the surface. Messaging should emphasize useful travel-money context rather than making unsupported claims about executable rates, exact fees or guaranteed savings.

### Canonical brand tagline

**Convert money. Understand local value. Discover culture.**

Use this as the stable brand-level line in repository/product identity surfaces unless there is a deliberate brand decision to replace it.

### Primary market-facing hero

**Convert money. Understand local value. Travel smarter.** — **96/100**

Alternative core value-proposition line:

**Convert money. Understand what it means there.** — **96/100**

Use this when the product needs to foreground its strongest differentiation: translating an amount into local meaning rather than merely displaying an exchange result.

Use this when the first job is to communicate practical travel value quickly. It preserves the product's local-value proposition while making the traveller benefit explicit.

Recommended supporting line:

**More than exchange rates — understand what your money means there.** — **95/100**

This is the strongest explanatory hero/subheadline because it states the product gap directly without implying that reference FX equals an executable bank/card rate.

### Product-positioning line

**A smarter currency converter for travelers.** — **93/100**

Use for concise product descriptions, directory/App-Store-style copy and portfolio summaries. Follow it with concrete capability copy rather than leaving “smarter” undefined.

Additional market-facing line:

**See what your money means there.** — **94/100**

Use when the surrounding surface already makes conversion explicit and the job is to communicate the product's distinctive local-meaning proposition in the fewest words.

Alternative category/hero line:

**Understand what your money means abroad.** — **95/100**

Use when the audience benefit should be explicit and travel-oriented without implying exact purchasing-power or payment certainty.

Emotional brand line:

**Bridging cultures through currency conversion.** — **86/100**

Use for brand story, portfolio narrative and cultural/editorial surfaces rather than as the primary utility headline.

### Utility / practical campaign lines

Approved high-value alternatives:

- **See what your money is really worth there.** — **95/100**
- **Know the rate. Know the place. Know your budget.** — **91/100**
- **Understand what your budget means abroad.** — **90/100**
- **Currency conversion with real-world context.** — **90/100**
- **Convert with context.** — **90/100**
- **See more than the rate.** — **92/100**
- **Let your money make sense wherever you go.** — **89/100**
- **Convert instantly. Plan confidently.** — **88/100**
- **A better way to understand money abroad.** — **88/100**
- **Make smarter spending decisions abroad.** — **86/100**
- **Understand the cost before you go.** — **87/100**
- **Convert fast. Understand more.** — **85/100**
- **Travel with clarity, not guesswork.** — **85/100**

These are campaign/section lines, not separate product promises. Use the one that matches the surrounding feature rather than rotating slogans arbitrarily.

### Emotional / cultural campaign lines

Approved when a surface intentionally emphasizes the cultural layer:

- **See the rate. Feel the country. Spend smarter.** — **88/100**
- **Convert money. Discover culture. Go with confidence.** — **87/100**
- **Travel beyond the exchange rate.** — **86/100**
- **Understand the rate. Discover the place.** — **84/100**
- **From currency to culture.** — **82/100**
- **Explore the world through money and meaning.** — **80/100**
- **See the rate. Feel the country.** — **82/100**

These should not replace practical rate/source/date information on conversion surfaces.

### Short product / App-style lines

Useful compact options:

- **Local value, instantly.** — **82/100**
- **Your money, in local context.** — **88/100**
- **Your travel money assistant.** — **87/100**
- **See the value behind the currency.** — **84/100**
- **Beyond the exchange rate.** — **86/100**
- **Where exchange meets understanding.** — **79/100**
- **Beyond exchange.** — **74/100**
- **Money meets culture.** — **76/100**
- **Travel smarter.** — **72/100**

Prefer the more specific options when the product name/logo is not already visible.

### Messaging cautions

Avoid or qualify copy that can overstate financial precision.

- **“Real rates. Real value. Real travel context.”** should not be a primary promise because “real rates” can sound like an executable or guaranteed bank/card rate. Prefer **“Reference rates. Local value. Travel context.”** when trust semantics matter.
- Avoid implying exact card, ATM, merchant or DCC outcomes unless they come from explicit user inputs or authoritative data.
- Avoid generic “smart” or “AI-powered” language without immediately showing the practical capability it refers to.
- Keep culture as a meaningful differentiator, but do not let cultural copy obscure the primary travel-money task.

### Recommended banner composition

**Headline:** Convert money. Understand local value. Travel smarter.

**Subheadline:** See reference exchange rates, local buying power, money tips and cultural context in one clear travel-money experience.

The subheadline deliberately says **reference exchange rates**, not “real exchange rates”, to remain aligned with the product trust model.

## Core experience

The intended loop is:

```text
Convert → Understand → Explore → Save → Return
```

### Retention model: trip-cycle habit

The product should not optimize for artificial daily usage across the whole year. Travel-money needs are naturally episodic. The healthier retention model is a **trip-cycle habit**:

```text
Discover destination
→ Create trip/scenario
→ Set budget
→ Save
→ Re-check before travel
→ Refresh/download destination context
→ Use during the trip
→ Track simple remaining budget
→ Finish trip
→ Reuse preferences for the next trip
```

The strongest retention mechanisms are continuity of state and point-of-use utility, not generic engagement mechanics.

Before travel, the product should make it easy to return to a saved scenario and understand what changed. During travel, the product should become more useful through fast conversion, camera-assisted price understanding, offline context and a lightweight remaining-budget view. After travel, it should preserve only the preferences and reusable assumptions that make the next trip faster to set up.

Avoid manufacturing retention through streaks, badges, random rate notifications, generic content feeds or forced login.

The signature interaction keeps source and destination identities visible together. Country context can change atmosphere and enrichment while the financial calculation remains stable and independently trustworthy.

## Primary users

The product is mainly for:

- travellers converting money before or during a trip;
- expats and international students building local intuition;
- cross-border shoppers comparing rough value;
- curious users exploring currencies and money culture.

## Current product capabilities

The web product currently supports:

- current FX conversion;
- historical FX conversion;
- explicit requested/effective observation dates;
- bilateral country/currency selection;
- historical trend views with 1Y / 5Y / 10Y / custom ranges, selected/minimum/maximum/last observations and Then & Now;
- smart country/currency filtering that respects shared, archived and date-scoped historical relationships while preserving currency-only choices;
- explicit-assumption Real Payment Estimate for current non-identity conversions, using signed trusted conversion snapshots plus user-entered FX markup and source/destination fixed fees;
- sourced current destination context;
- everyday-value examples;
- cash/card/ATM/tipping guidance;
- deterministic money/culture storytelling;
- optional AI explanation;
- anonymous local favourites/recent conversions;
- account-owned favourites;
- separately opt-in account recent history.

Current Real Payment Estimate does not persist a reusable fee profile and does not estimate historical card/ATM/merchant costs. Those remain future work.

Current code and tests are the authoritative detail for these capabilities.

## Product principles

### Utility first

A user should be able to convert money quickly without consuming enrichment.

### Context is progressive

Useful destination context should be close to the conversion result. Deeper history/culture can be opened when desired.

### Trust is visible

Rates, historical observations, typical prices and factual cultural claims should carry enough provenance and timing context to avoid false precision.

### Current and historical meaning are separate

Historical FX does not automatically make today’s prices or payment customs historical. Current context should be clearly labelled when shown next to a historical conversion.

### Optional systems are optional

Media, external enrichment and AI should degrade gracefully. Core conversion should not depend on them.

### Country and currency are distinct

A currency can belong to multiple countries and country/currency relationships change over time. Product language and data modelling should preserve that distinction.

### Feature decision guardrail

Before adding a meaningful product capability, ask:

1. Does it help the user understand their money?
2. Does it help them understand the place?
3. Does it help them make a better travel-money decision?
4. Does it add cultural value without adding noise?
5. Can it stay off the critical conversion path?

If the answers are mostly no, the feature should not enter the core product.

### Product North Star

**Does this help the user better understand or use their money in another country?**

This is the shortest decision test for new product work. A feature that cannot answer it clearly should remain outside the core experience.

### Tone of voice

The product voice is **clear utility + warm intelligence + cultural restraint**.

Prefer copy that is calm, concise, human and specific. Avoid tourism clichés, financial jargon for its own sake and vague “AI-powered intelligence” language.

## Product measurement

When product analytics are introduced, prefer a small privacy-conscious measurement set tied to real user value rather than vanity events.

Useful candidate measures include:

- successful first conversion;
- local-context engagement;
- compare usage;
- saved-scenario creation;
- saved-scenario reopen / pre-trip return;
- optional AI quick-prompt usage;
- share-card usage;
- D1 / D7 / D30 return where lawful and proportionate.

### Retention measurement priority

Do not treat generic DAU as the primary success metric for this product. Prefer metrics that reflect the natural travel lifecycle:

1. **Saved Trip / Scenario → Reopen rate** — whether planning state creates a reason to return.
2. **Active Trip → Uses per travel day** — whether the product is genuinely useful at the point of use.
3. **Completed Trip → Return for next trip** — whether the product earns long-term trust and reuse.

Supporting measures can include pre-trip re-check completion, offline-pack refresh/use, camera-to-confirmed-conversion completion, add-to-trip usage, and the percentage of returning users who can start a new trip without re-entering unchanged preferences.

Measurement must not silently turn sensitive travel/financial context into broad behavioural tracking. Collect only what is needed to evaluate product usefulness, document retention, and respect user/account privacy boundaries.

## Market strategy and monetization guardrails

The main product risks are not only technical. The product should explicitly watch:

- **distribution** — a good converter does not automatically acquire users;
- **retention** — currency conversion is naturally episodic unless saved trips, re-checks, comparison and discovery create a reason to return;
- **monetization** — basic conversion alone is a weak recurring-subscription proposition;
- **defensibility** — FX, payment tips and simple local-price cards can be copied, so data quality, scope/provenance, context composition and user workflows matter more than feature count.

Initial monetization should remain a hypothesis, not a requirement for the core product.

A plausible future freemium boundary is:

- **Free:** conversion, core local context, basic culture/history and limited saved state;
- **Travel Pro candidate:** offline destination packs, camera-assisted price understanding, deeper trip/budget workflows, multiple saved trips/comparisons and user-configured payment-fee profiles.

Affiliate or partner revenue may be explored only when it does not bias factual guidance or weaken trust. Commercial relationships must never determine which rate, payment warning or local-money recommendation is presented as factual truth.

## Non-goals

The product is not intended to be:

- a trading terminal;
- a remittance execution service;
- a bank/accounting ledger;
- regulated financial advice;
- a guarantee of merchant/card/ATM fees;
- a universal cost-of-living database;
- a source of unsourced historical or cultural claims.

## Future direction

Likely future areas include:

- a versioned mobile API;
- a native mobile client;
- trip/budget workflows;
- richer sourced destination data;
- research into historical purchasing power.

These are directions, not fixed implementation commitments. Technology choices should be re-evaluated when each area becomes active.
