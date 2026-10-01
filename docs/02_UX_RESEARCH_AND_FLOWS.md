# UX

## Experience goal

The product should feel like a trustworthy currency converter that gradually reveals useful local meaning.

The primary screen should answer the conversion task first and make deeper exploration discoverable without overwhelming the user.

## Primary flow

A typical flow is:

1. enter an amount;
2. choose source country/currency;
3. choose destination country/currency;
4. convert;
5. inspect rate/source/date information;
6. optionally explore everyday value, payment context, money/culture or history;
7. optionally save/repeat the pair.

Country selection is useful context, but currency-only conversion should remain possible when country context is unknown or irrelevant.

## Bilateral workspace

Source and destination should remain understandable at the same time.

On wider layouts they may appear side by side. On narrow layouts they can stack while preserving the same semantic and keyboard order.

Avoid repeating country/currency wording in multiple adjacent controls when one clear identity label is enough.

## Current country/currency picker behaviour

The shipped picker searches country/currency options through temporal country/currency relationships.

Current behaviour includes:

- country-context options and currency-only options;
- current selection labelling;
- historical labelling for archived/date-scoped options;
- date-aware option lookup in historical mode;
- preservation of currency-only conversion when country context is unnecessary.

Form validation remains the final authority: a submitted country/currency mismatch is rejected before any FX provider call.

## Core states

### Initial

Show a clear amount field, source/destination selectors and a primary Convert action.

### Editing

Preserve user input while selections change. Do not erase a valid previous result merely because the user is preparing the next request.

### Loading/updating

Show progress without causing avoidable layout shifts. Existing trustworthy information may remain visible while a refresh is pending if its status is clear.

### Success

Emphasize:

1. converted amount;
2. rate/date/source trust context;
3. contextual interpretation;
4. secondary save/explore actions.

### Validation error

Keep entered values. Explain the problem close to the field and provide a useful error summary when multiple fields fail.

### Provider/degraded state

Explain whether the result is unavailable, stale or using a safe fallback. Do not silently transform a failure into apparently fresh data.

### Empty enrichment

If price/culture/media data is missing, show a concise neutral state or omit the block. Never fabricate filler.

## Historical conversion

Historical mode should make the temporal boundary obvious:

- requested date can differ from the provider’s effective observation date;
- archived currencies are legitimate historical entities;
- historical FX and historical purchasing power are separate concepts;
- current payment/price context should not be backdated implicitly.

Historical charts and Then & Now are explanatory features, not trading/investment surfaces.

## Current Real Payment Estimate

The shipped current-conversion flow includes a progressive Real Payment Estimate for non-identity currency pairs.

It starts from a signed trusted conversion snapshot and accepts only explicit user assumptions:

- FX markup percentage;
- a fixed fee in the source currency;
- a fixed fee in the destination currency.

The result shows the estimated destination value and the difference from the trusted reference conversion. Currency-specific minor-unit rounding is preserved.

Important current boundaries:

- current reference conversions only;
- no estimate for exact same-currency 1:1 conversion;
- no inferred bank/card/ATM/DCC/merchant fee;
- no historical payment-cost estimate;
- no reusable saved fee profile yet;
- HTMX enhancement has a full-page no-JavaScript fallback.

This is a scenario estimate, not an executable quote.

## Local meaning as a primary contextual surface

After the trusted conversion result, the strongest contextual question is:

**What does this amount mean here?**

Everyday-value anchors should be treated as a primary product surface, not a novelty card buried beneath culture or AI. The UX can summarize categories such as food, transport, coffee or other sourced local spending anchors without implying universal prices.

Prefer a small number of useful, scoped examples over a long list. City/country scope, freshness and uncertainty should remain visible enough to prevent false precision.

## Explore layer

The compact first-level exploration is:

- **Everyday value** — sourced examples that help interpret an amount;
- **Payment context** — cash/card/ATM/tipping guidance;
- **Money & culture** — deterministic factual stories.

These paths can evolve. Their purpose is more important than a fixed card layout.

### One useful insight at a time

Progressive context should prioritize the most useful next insight rather than showing every possible warning, fact and recommendation at once. A single strong payment warning or local-value takeaway is usually better than a dense advice grid.

## Contextual AI interaction

AI should not open as an empty general-purpose chat box by default. When AI adds value, prefer context-aware entry points derived from the current conversion, destination or saved scenario.

A useful pattern is:

- **Smart result summary** — one short sentence explaining the most relevant implication of trusted conversion/context data;
- **Quick prompts** — a small set of relevant next questions such as budget fit, cash need, payment warning or destination comparison;
- **Structured insight panel** — short answer, what matters most, one caution and a useful next action.

AI answers must remain downstream of trusted structured data. The interface should make it easy to dismiss or ignore AI without weakening the core conversion experience.

## Cultural-history portal

A compact progressive-disclosure surface may combine the deeper **Money & culture** experience into one coherent portal. The entry point can be a labelled button or icon, but it must not rely on an unexplained “?” glyph for meaning.

A useful structure is:

- quick cultural snapshot;
- currency fact;
- previous-currency context where historically relevant;
- local money etiquette;
- one concise travel-money tip;
- one memorable sourced fact.

The portal should normally be readable in well under a minute. It is not a general help dialog and should not become an encyclopedia.

## Historical quick exploration

The shipped historical-series surface exposes **1 year / 5 years / 10 years** plus a custom range when provider coverage supports it.

Current presentation includes:

- the normalized chart;
- selected, minimum, maximum and last observations when present;
- provider attribution and stale state;
- requested/effective-date context;
- a concise summary derived from the actual series;
- Then & Now comparison where the required observations are available.

Do not turn range controls into a trading surface, and do not invent continuity where historical observations are missing.

## Destination mode

A future **Destination mode** can let the user start from the place they are in or are travelling to rather than from a currency pair.

A simple explicit flow is:

**I’m in / I’m going to → country or city → local currency + money context**

The product can then preselect the relevant current currency, everyday-value context, payment guidance and saved-trip actions while preserving the ability to change currency manually.

Do not require precise device location for this mode. Manual destination selection must always work. If location assistance is ever added, it should be opt-in, coarse enough for the task and never silently persisted as travel history.

## Discovery / Explore experience

A future Explore surface can make the product useful even when the user is not performing an immediate conversion.

Potential discovery collections include:

- what the same source amount roughly means across destinations;
- card-first versus cash-relevant destinations;
- currency stories and historical transitions;
- region-based exploration;
- destination alternatives with comparable sourced money context.

Discovery rankings or labels should appear only when the underlying data is comparable enough to support them. Avoid pseudo-precise global “cheapest/most expensive” claims built from inconsistent country or city data.

## Saved and recent state

Anonymous browser storage is useful for convenience but should be described as local-only. Browser-local controls that require JavaScript should not render as inert actions before enhancement, and empty-state claims should appear only after the browser state has actually been inspected.

Repeated saved/recent row actions should keep concise visible verbs while exposing row-specific accessible names. Collection-wide clear operations are destructive actions and should be visually distinguishable from routine secondary navigation without adding unnecessary confirmation friction.

Signed-in data should respect ownership. Cross-device recent history is separately opt-in; signing in should not silently upload existing local recent activity.

### Actionable history

History should support useful re-entry, not only archival viewing. Where the required data exists, a previous conversion may offer concise actions such as:

- repeat/reopen;
- compare destination;
- save as a scenario/trip;
- open the relevant cultural/history context;
- ask a bounded AI question about the saved conversion.

Do not expose actions that cannot preserve the original rate/date/source semantics.

## Returning-user home

For a new or anonymous user, the primary entry can remain converter-first. For a returning user with an upcoming saved trip, the home surface should prioritize continuity.

A useful returning-user summary can show:

- upcoming destination and dates;
- saved budget and approximate daily amount;
- latest reference conversion and change since the last saved observation;
- destination-context/offline-pack freshness;
- concise quick actions such as **Scan price**, **Check budget**, **Money tips** and **Open trip**.

Do not turn this into a dense travel dashboard. The purpose is to remove repeated setup and surface the next useful action.

## Trip-cycle retention flow

Saved scenarios should support a deliberate lifecycle rather than ending at a bookmark:

**Plan → Save → Re-check → Travel → Use → Finish → Next trip**

### Before travel

When a user reopens a saved scenario, the product can surface:

- the latest reference observation;
- the change from the last relevant saved observation;
- refreshed local-value/payment context;
- whether the saved budget interpretation changed under the same explicit assumptions;
- destination-pack freshness and whether an offline refresh is useful.

The shipped account scenario detail supports an explicit reference-rate re-check. It reuses the exact saved source amount/currency pair, appends a new immutable observation only when the provider observation is distinct, and compares the latest stored reference with the original saved observation. The copy uses neutral **more / less / unchanged** language for the same source amount and never frames the movement as a recommendation to exchange money.

Provider failure must leave the saved scenario and its original observations unchanged. Repeated checks of the same effective provider observation should not create duplicate history rows.

The shipped save flow can optionally store a travel start/end date. Saved scenario detail derives a deterministic **upcoming / active / started-without-end / ended** readiness state from those explicit dates. A saved end date requires a start date at form, domain and database boundaries. Timing metadata must never imply a hidden itinerary, auto-refresh or notification subscription.

Optional pre-trip reminders may later invite the user to re-check a saved scenario close to its travel date. Reminder delivery must be explicit opt-in, easy to disable and separate from rate-alert/trading-style messaging.

### During travel

The saved trip should become a fast point-of-use surface rather than forcing the user back through setup. Useful actions include:

- convert a price immediately;
- scan a menu, receipt, shelf price or ATM screen;
- confirm the extracted amount/currency before any financial calculation;
- optionally add a confirmed expense amount to the active trip;
- see a simple remaining budget and approximate amount-per-day remaining;
- open destination payment/ATM/DCC guidance;
- use explicitly stale-labelled offline context when connectivity is limited.

The budget view should remain intentionally lightweight. It is not a general bookkeeping or expense-management product.

### After travel

The product may preserve reusable preferences such as home currency, language, travel style and explicit fee assumptions when the user has chosen to save them. Starting the next trip should reuse these defaults without silently copying destination-specific spending history or building a sensitive travel profile.

### Scenario-based notifications

Notifications should be tied to a saved scenario or upcoming trip, not generic market noise.

Prefer messages such as:

- the saved trip budget now converts to a materially different local amount;
- the trip starts soon and destination money context should be re-checked;
- an offline destination pack is old enough to refresh before travel.

Avoid messages that encourage timing the FX market or imply that a rate move is a recommendation to exchange money.


## Accessibility

Key expectations:

- full keyboard operation;
- visible focus;
- useful labels and error associations;
- no state communicated only through colour;
- sensible live-region announcements;
- resilient reflow and text zoom;
- reduced-motion support;
- touch targets that remain practical on mobile.

Exact CSS dimensions are implementation details unless needed to satisfy an accessibility requirement.

## Responsive behaviour

Design from semantic order first.

Prefer:

- natural DOM order;
- no CSS-only reordering that changes reading/focus meaning;
- containers that can wrap and reflow;
- full-screen or roomy picker treatment on compact devices when it improves usability.

Test the real interaction on narrow widths rather than only inspecting screenshots.

## UX change policy

A UX pattern is not permanent because it appears in this document.

When evidence, browser QA or user value suggests a better pattern:

1. improve the experience;
2. protect the new behaviour with appropriate tests;
3. update this document if the product-level interaction meaning changed.


## Budget interpretation flow

The first shipped budget UX is a transparent reference-basket comparison layered on top of a trusted current conversion.

**Conversion → Budget interpretation → Edit assumptions → Compare**

The progressive surface should:

- start from the signed conversion result rather than trusting a posted reference amount;
- require a destination country and current sourced price anchors;
- keep trip duration and traveller count explicit;
- expose the actual daily reference items and editable units per person/day;
- preserve city versus national scope and source/provenance for every line;
- show available destination amount, per-person daily amount and the known basket range;
- use neutral labels such as **below reference / within reference / above reference** rather than universal “cheap”, “expensive”, “comfortable” or financial-advice language;
- return **insufficient data** rather than inventing a band when selected categories cannot be supported;
- work with HTMX enhancement and as a complete no-JavaScript page.

The current slice uses the reference conversion basis in the UI. The domain already supports an attached explicit Real Payment Estimate basis, but that should only become a user-facing option once the payment-assumption handoff is designed so the exact assumptions remain visible and trustworthy.

Budget interpretation is not a full trip-cost forecast. Accommodation, flights and unselected categories must never be silently added.

### Saved budget handoff

After a successful budget interpretation, a signed-in user may explicitly save that planning state.

The save handoff must preserve these boundaries:

- the trusted conversion and destination scope come from the signed budget-context token;
- only the explicit duration, traveller count and selected daily basket assumptions are persisted;
- saving does not silently copy browser-only favourites or recent history;
- the save action does not require a second live local-price lookup after the interpretation has already been produced;
- the saved detail page shows the stored assumptions and immutable FX observation as saved, rather than silently refreshing them;
- **Re-run conversion** is an explicit action and future **Re-check** must append a new observation rather than overwrite the original;
- owner scoping applies to view and delete operations;
- anonymous users get an opt-in sign-in affordance rather than silent account persistence.

The current saved-budget detail is intentionally narrow. Current local-value refresh, rate-change comparison, remaining-spend tracking and trip-day workflows belong to later scenario iterations.

