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

Historical analysis can expose simple user-oriented ranges such as **1 year / 5 years / 10 years** when the provider has defensible coverage.

Prefer:

- a simple chart;
- a small number of anchor values;
- requested/effective-date meaning;
- a concise human-readable explanation grounded in the actual series.

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

## Re-check and pre-trip return flow

Saved scenarios should eventually support a deliberate return loop:

**Plan → Save → Re-check → Travel**

When a user reopens a saved scenario, the product can surface:

- the latest reference observation;
- the change from the last relevant saved observation;
- refreshed local-value/payment context;
- whether the saved budget interpretation changed under the same explicit assumptions.

Optional pre-trip reminders may invite the user to re-check a saved scenario close to its travel date. Reminder delivery must be opt-in, easy to disable and separate from rate-alert/trading-style messaging.

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
