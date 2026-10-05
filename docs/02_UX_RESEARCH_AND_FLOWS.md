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
- signed-in users may save named reusable fee profiles for the exact source/destination currency pair; applying one replaces only the explicit assumption fields and never the signed reference conversion;
- HTMX enhancement has a full-page no-JavaScript fallback.

This is a scenario estimate, not an executable quote.

A saved fee profile is deliberately pair-scoped because fixed fees carry currency meaning. It stores only a name, source/destination currencies, FX-markup assumption and source/destination fixed-fee assumptions. Profiles are account-owned, capped, manually saved from a validated Payment Estimate and manually applied. The product does not infer a bank/card/ATM provider or auto-apply a profile from history.

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

The first Smart result summary slice is now shipped as a deterministic part of the successful conversion result, before optional AI. It uses one concise sentence, keeps historical/stale/exact trust meaning ahead of destination enrichment and may reference only reviewed local-price/payment context already shown by the product. This keeps the top-line implication useful without turning it into a recommendation, hidden ranking or generated factual layer.

Explore now reuses the same trust boundary for destination-level AI: there is no empty chatbot and no arbitrary prompt. The user selects one reviewed destination plus a bounded intent such as overview, cash/card or price evidence. The server revalidates that destination against current Explore state, rebuilds trusted DestinationContext and sends only structured fact IDs/values to the existing validated explanation stack. Provider failure falls back deterministically and does not weaken discovery truth.

Budget Interpretation and Destination Comparison now follow a stricter post-result pattern. After the deterministic calculation finishes, the server creates one bounded structured fact packet per suggested question and signs the entire packet plus its capability. The browser sends only that signed packet to the explanation endpoint; it cannot edit the intent, rate, converted amount, basket totals, coverage or destination scopes. Budget and comparison explanations therefore remain optional interpretation layers over an unchanged deterministic result, with no additional FX request and no destination-ranking or affordability verdict.

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

The first **Destination mode** slice is implemented as a manual destination-first entry point.

The current explicit flow is:

**Amount + source currency → country or canonical city → current primary local currency → canonical converter + Money Context**

Current UX rules:

- manual destination selection is the baseline and requires no device location;
- country choices resolve through current primary CountryCurrency relationships;
- city choices use canonical active City records and preserve city scope into the converter;
- the destination page itself does not request an FX rate;
- the trusted conversion, provider attribution, effective date, stale state and downstream payment/budget semantics remain owned by the canonical converter/Money Context path;
- changing the destination country or swapping sides clears stale city scope rather than applying a city to the wrong country;
- users can still change currency manually once they reach the converter.

My Places now supports both browser-local and owner-scoped account persistence for reviewed Explore country/city scopes. Anonymous saves remain device-local. Signed-in saves go directly to the account, while older browser-local places move only through an explicit import control on Saved & recent; sign-in alone never migrates them. Account re-entry resolves current currency from canonical country/currency relationships rather than replaying a stored currency snapshot. Optional coarse location assistance remains future work and must stay opt-in.


## Shopping calculation flow

Shopping is an explicit foreign-purchase planning surface, not a second converter engine.

**Item price + shipping + known fees → purchase-currency total → current reference FX → home-currency reference cost → optional markup assumption**

- the entry GET performs no FX request;
- purchase country is optional, but when supplied its current currency relationship is validated before provider access;
- purchase currency and home currency must differ;
- item price, shipping and known fees are all purchase-currency inputs;
- only the explicit total is sent through the canonical current FX path;
- optional FX markup is labelled as a user assumption and shown separately from the reference cost;
- provider/effective-date/stale semantics stay visible;
- duties, taxes and issuer/merchant fees remain unknown unless the user explicitly supplies a known fee;
- provider failure keeps the bound form intact and never substitutes a guessed result;
- the workflow remains usable without JavaScript.

Shopping persistence reuses SavedScenario rather than introducing a parallel save model. A signed Shopping result handoff binds the exact explicit inputs to the exact trusted current FX observation. Saving creates an account-owned Shopping scenario with a normalized one-to-one assumptions payload plus the shared immutable initial observation. Detail/reopen shows the original saved estimate, while explicit rate re-checks append observation history without changing that baseline. Reopen repopulates the Shopping form without provider access; a new rate is requested only after the user explicitly submits again.


## Destination comparison flow

The shipped comparison surface answers a bounded question: **what does the same source budget roughly mean across two explicit destinations under the same visible assumptions?**

The current flow is:

**Source amount/currency → Destination A + Destination B → shared duration/traveller/reference basket → two trusted conversions → side-by-side Money Context**

UX rules:

- the GET/entry page is provider-free; current rates are requested only after explicit submit;
- both sides use the canonical current converter/Money Context path rather than a comparison-specific rate calculation;
- country and canonical-city scope remain explicit per side;
- each side keeps its own rate provider/effective date/stale state, price provenance and payment guidance;
- the same visible basket assumptions apply to both sides;
- missing categories stay visible as partial coverage instead of being guessed;
- comparison language stays descriptive: no winner, no “cheapest destination”, no PPP claim and no direct cross-currency price ratio;
- a provider failure on either required side produces a neutral recoverable state rather than silently comparing one real side with one inferred side;
- the surface remains usable without JavaScript and has browser QA coverage.

SavedComparison continuity is now shipped for authenticated users as input-only persistence: amount, source currency, two canonical destination scopes, duration, travelers and basket assumptions are saved, while rates, local-price results and rankings are not. Reopen restores those inputs provider-free; Re-check explicitly reruns the canonical comparison path. Explore, My Places, saved scenarios, favourites and recent conversions can seed exactly one canonical Destination Comparison side when they already know a destination; the second side and all comparison assumptions remain explicit user choices.

## Discovery / Explore experience

Explore is now a provider-free GET over reviewed current destination context with five provenance-bearing deterministic collections and canonical region → country → city navigation. Direct city evidence is required before a city scope is exposed; national fallback remains visibly scoped. Unknown geography falls into an explicit reviewed fallback group rather than disappearing.

Current Explore actions can:

- open the canonical Converter or City Money Profile with exact country/city scope;
- seed exactly one side of Destination Comparison without choosing a peer;
- save/remove reviewed country/city identity in browser-local My Places;
- open Same Amount Across Destinations, where one source amount is viewed across two to four explicit destinations without ranking;
- request a bounded contextual AI explanation only after the user explicitly chooses a reviewed destination and server-approved intent.

Explore GET itself performs no live FX or AI call. The AI POST rebuilds trusted current context server-side and sends only a bounded structured fact packet; it cannot manufacture discovery cards, FX, prices, payment guidance, affordability, PPP or rankings.

Future discovery expansion may still add richer destination alternatives or additional evidence-backed cash/card-oriented exploration, but only when the underlying data is comparable enough to support it. Avoid pseudo-precise global “cheapest/most expensive” claims built from inconsistent country or city data.

## Saved and recent state

Anonymous browser storage is useful for convenience but should be described as local-only. Browser-local controls that require JavaScript should not render as inert actions before enhancement, and empty-state claims should appear only after the browser state has actually been inspected.

Repeated saved/recent row actions should keep concise visible verbs while exposing row-specific accessible names. Collection-wide clear operations are destructive actions and should be visually distinguishable from routine secondary navigation without adding unnecessary confirmation friction.

Signed-in data should respect ownership. Cross-device recent history is separately opt-in; signing in should not silently upload existing local recent activity.

**Current continuity slice:** Saved & recent now gives account-owned scenarios, SavedComparison, My Places, favourites and opt-in recent history a restrained hierarchy beside remaining browser-local places/favourites/recent conversions. Primary actions reopen canonical flows, destructive actions remain explicit, and browser-local place migration is opt-in. SavedComparison makes the trust distinction visible: **Reopen inputs** is provider-free and restores the form only; **Re-check now** explicitly submits the saved inputs through canonical Compare and requests current reference values.

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

**Current production slice:** on a clean authenticated converter home, the product selects one account-owned active/started/upcoming trip without making a live FX request. Active travel takes priority, then a started trip without an end date, then the nearest upcoming trip. The surface can show remaining saved-trip budget, the latest stored re-check difference from the immutable saved baseline, reviewed city/country context freshness and quick actions into the saved trip, Camera or offline pack. Anonymous users, explicit conversion deep links, loaded pairs, ended trips and unscheduled scenarios remain converter-first.

### Camera confirmation → trip budget handoff

Camera extraction and spend persistence remain two separate user decisions.

After the user confirms or corrects an extracted amount:

1. the page shows the confirmed destination-currency amount;
2. no spend is written yet;
3. **Add to trip budget** performs a separate CSRF-protected POST;
4. the server reloads and verifies the short-lived scenario-scoped signed confirmation token;
5. the signed token—not an editable amount field—is the authoritative handoff value;
6. the existing idempotent saved-scenario spend service records only amount, source and timestamp;
7. the token carries a signed unique confirmation id used as the spend idempotency key, so replaying the same confirmation cannot double-count spend while a separate confirmation remains distinct.

A user can always return without adding the amount. The source image, receipt text and merchant identity remain outside saved-trip persistence.

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

Current local money context is a separate explicit refresh. Opening the saved detail page performs no local-price lookup. **Refresh local money guide** rebuilds reviewed destination price/payment context through the canonical DestinationContext contract, uses the latest already-stored FX output only as the amount anchor for purchase examples and persists nothing. Empty or unavailable context degrades locally without changing the saved scenario, its observation history or Trip Budget Remaining.

Provider failure must leave the saved scenario and its original observations unchanged. Repeated checks of the same effective provider observation should not create duplicate history rows.

The shipped save flow can optionally store a travel start/end date. Saved scenario detail derives a deterministic **upcoming / active / started-without-end / ended** readiness state from those explicit dates. A saved end date requires a start date at form, domain and database boundaries. Timing metadata must never imply a hidden itinerary, auto-refresh or notification subscription.

Scenario-based in-app notifications are now explicit end to end. A saved scenario can opt into a pre-trip reminder, context/offline freshness reminder or rate alert; type, enabled state, IANA timezone, cadence and channel are stored independently from financial observations. Pre-trip opt-in still requires an explicit saved travel start date. Rate alerts require an explicit percentage threshold and compare a transient canonical current quote with the immutable initial observation without persisting the probe as scenario history. Due generation is repeat-safe: local calendar cadence plus a database dedupe key prevents duplicate messages when the scheduler retries, and last-delivered time remains visible to the user. Provider/stale failures create no rate alert. Disable/delete and read/unread actions remain owner-scoped, and all wording stays informational rather than encouraging exchange timing.

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

The first shipped remaining-budget slice is account-owned and explicit:

- the immutable **initial saved FX observation** establishes the destination-currency reference budget;
- later FX re-checks can inform the separate since-saved comparison but never move the remaining-budget baseline;
- only user-confirmed destination-currency amounts are subtracted;
- manual entries store amount, confirmation source and timestamp, not merchant/receipt/free-text purchase history;
- corrections use explicit remove-and-add behaviour rather than silently editing history;
- remaining-per-day uses the explicit saved travel window when both dates exist, otherwise an explicit planning duration only when that does not pretend to know how many travel days remain;
- an ended trip or a started trip with no end date keeps the remaining amount visible but does not invent a per-day figure.

The Camera flow for saved budget scenarios is explicit end to end:

- entry is explicit; no camera/device access occurs without the user selecting/capturing a file;
- accepted uploads are JPEG/PNG/WebP, bounded to 8 MiB and a bounded decoded image size;
- the application strips metadata/orientation ambiguity by decoding and re-encoding the image in memory before any provider call;
- raw uploaded media is not persisted by the application;
- the provider is asked for monetary amount candidates only, not surrounding receipt/menu/account content;
- an explicit detected currency that conflicts with the saved scenario currency cannot cross the confirmation boundary;
- the user can correct the amount before confirmation;
- confirmation creates a short-lived signed amount/currency/scope token with a unique confirmation id and still performs no spend write;
- **Add to trip budget** is a second explicit action that re-verifies the token and persists through the same idempotent Trip Budget Remaining contract used by manual spend;
- replaying one confirmation cannot double-count spend, while a separately confirmed identical amount remains a separate user action.


### Offline destination pack

The installable web shell is now a separate progressive-enhancement layer from trip snapshots. When the network is unavailable, ordinary navigation falls back to a generic offline page that contains no account or scenario data. The service worker never caches navigation HTML, so signing in, opening Saved, editing a scenario or viewing notifications cannot silently leave private pages in Cache Storage. Only public build/PWA assets and the generic offline shell are eligible for service-worker caching.

The portable offline slice is a deliberate download from an account-owned saved budget scenario, not a hidden cache.

The exported HTML file is self-contained: it carries its own restrained styling, no executable scripts and no remote asset dependency. It includes:

- the newest already-stored FX observation, with amount, rate, provider attribution, effective date, fetch time and stored stale flag;
- Trip Budget Remaining derived from the immutable initial saved FX observation and confirmed spend;
- saved destination/city and explicit trip timing assumptions;
- currently reviewed local-price anchors and payment guidance with scope, observation/verification dates and provenance;
- an explicit pack-generation timestamp and versioned pack-format marker.

The file must say clearly that **offline means stored, not live**. Opening it later never refreshes FX or context. A user who wants fresher meaning must return online, explicitly re-check as needed and download a new pack.

If local destination context is unavailable while generating the file, the pack still exports the saved FX/budget state and shows a degraded context notice instead of inventing prices or advice.

The pack intentionally excludes receipt images, merchant identities, account/card data and individual purchase descriptions. Because the file may still contain a user’s saved budget/travel details, the download UI should remind the user to store it privately.

The installed-app active-trip slice is explicit rather than automatic. On an authenticated saved budget scenario, **Save trip for offline** fetches the same canonical snapshot representation and stores it in a dedicated private Cache Storage namespace only after the click. The service worker itself never writes private scenario data. The generic offline shell can list only these explicit device copies and route an offline saved-scenario navigation to its matching read-only snapshot.

Lifecycle stays visible:

- a snapshot carries a version, generated timestamp and deterministic saved-scenario revision;
- confirmed spend, a new stored FX observation or saved planning changes make the device copy **out of date** on the next online reopen;
- **Refresh offline copy** explicitly replaces that snapshot;
- snapshots older than 24 hours receive a conservative refresh reminder even if the saved-scenario revision is unchanged;
- **Remove offline copy** deletes both the private cache entry and its local metadata;
- returning to an anonymous page after sign-out clears private PWA trip storage as a privacy backstop.

The offline app snapshot is still **stored, not live**. It never refreshes FX while offline, never turns reviewed context into current truth merely because the page opens, and remains read-only. The portable HTML pack continues to work independently when service workers, Cache Storage or JavaScript are unavailable.


### After travel

The product may preserve reusable preferences such as home currency, language, travel style and explicit fee assumptions when the user has chosen to save them. Starting the next trip should reuse these defaults without silently copying destination-specific spending history or building a sensitive travel profile.

The first shipped preference is home currency. Account → Home currency is the only place that creates or clears this default. Fresh Converter, Destination Mode and Destination Comparison may use it as their starting source currency; explicit deep links/reopen state and all submitted values win over the preference. An unavailable preference lookup degrades to the product's ordinary default instead of blocking planning.

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

### Reusable budget presets

After a successful interpretation, a signed-in user may save the current **assumption bundle** as a named budget preset. A preset contains only duration, traveler count and selected daily category units. It deliberately omits destination, currency, FX, current price anchors, payment-estimate basis and result labels.

Applying a preset is an explicit submit action. It replaces the current assumption fields and immediately reruns the deterministic interpretation against the current signed planning context. Categories saved in the preset remain explicit even when the current destination lacks a sourced anchor; the result then shows **Insufficient current data** rather than silently dropping that category.

Presets are owner-scoped, capped, listed in Account and deletable there. Saving the same name updates that user's existing preset instead of multiplying duplicates.

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

The current saved-budget detail remains intentionally narrower than a full travel ledger. Rate-change comparison, deterministic trip readiness, explicit Trip Budget Remaining, explicit Camera-confirmed spend and explicit current local-money-guide refresh are now present. Automatic/background context refresh and deeper trip-day workflows remain later iterations.

