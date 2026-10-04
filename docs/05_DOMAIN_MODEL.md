# Domain Model

This document describes the meaning of the main concepts. Field-level details live in Django models and migrations.

## Country

A geographic/political country identity used for travel context.

Important distinction: a country is not a currency.

Typical identity fields include ISO codes and display name.

## City

A canonical city identity scoped to one country.

The city slug is the stable product identifier used by current city-level Money Context, Budget, Destination Comparison, Explore/City Money Profile and both browser-local and account-owned My Places flows. Display names may evolve without changing saved references. A city slug is unique only within its country.

## Currency

A monetary unit identified by a currency code plus metadata such as name, symbol and decimal behaviour.

Historical/archived currencies remain valid domain entities.

## CountryCurrency

Represents a country ↔ currency relationship over a period of time.

This supports:

- shared currencies;
- historical currency transitions;
- country-first selection for a requested date.

Temporal boundaries are part of the relationship, not inferred from current data.

Primary-currency periods for the same country are inclusive, non-overlapping intervals. Adjacent eras are valid; ambiguous or overlapping eras fail closed rather than relying on query ordering. Supported model writes serialize on the country row before validating this invariant, while database uniqueness constraints remain a second line of defense for active relationships.

## FX quote / conversion result

A normalized quote/result should carry enough information to explain its financial meaning:

- base/quote currency;
- rate;
- requested date/mode;
- effective observation date when applicable;
- provider/provenance;
- stale/reference/exact semantics where relevant.

Money and rate arithmetic uses `Decimal`.

## Historical series

A time series represents normalized FX observations for a pair and interval.

Chart presentation should not invent observations or imply trading-quality market data.

## Trusted conversion snapshot

A signed trusted conversion snapshot carries the already-established conversion inputs/results needed by optional follow-up calculations without trusting editable browser fields as financial truth.

The current payment-estimate flow uses this boundary so a user cannot replace the reference amount/rate by posting arbitrary hidden fields.

A trusted snapshot is not a new FX observation and does not extend the freshness or historical meaning of the underlying quote.

## MoneyContext

A MoneyContext composes one trusted `ConversionResult` with optional current destination meaning.

Its stable destination identity consists of a country code plus an optional canonical city slug. City scope never changes conversion truth; it only narrows optional local-value enrichment. If returned destination enrichment identifies a different city than the requested MoneyContext scope, the enrichment degrades rather than being exposed as trusted context.

Historical conversion remains financially valid but current city/destination enrichment stays not-applicable unless a separate historical context dataset exists.

## BudgetInterpretation

A budget interpretation is a deterministic comparison between one trusted current MoneyContext amount and an explicit daily reference basket.

Its assumptions are intentionally narrow:

- trip duration in days;
- traveller count;
- one or more unique category assumptions expressed as units per person per day;
- an explicit amount basis: reference conversion or an attached Real Payment Estimate.

The engine uses only sourced `TypicalPriceContext` rows already present in the MoneyContext. A country-level budget does not silently treat a city observation as nationally representative. A city-level budget may combine the requested city with clearly labelled national fallback rows when the destination-context layer supplied them.

The result carries known low/high reference totals, per-person daily budget, source/scope metadata for each matched line and any missing categories. If a requested category is missing, the interpretation is **insufficient data** and no affordability band is guessed.

Current neutral bands are **below reference**, **within reference range** and **above reference range**. They compare only against the explicit reference basket; they are not universal “cheap/expensive”, lifestyle or financial-advice labels.

Historical FX is not eligible for current budget interpretation because current typical-price context is not historical purchasing-power data.

## DestinationComparison

A DestinationComparison is a deterministic side-by-side interpretation of the **same source amount and source currency** across two different current destination scopes.

The first domain slice deliberately reuses:

- one trusted MoneyContext per destination;
- the same explicit BudgetAssumptions on both sides;
- each destination's full ConversionResult, including effective-date/provider/stale semantics;
- each destination's own quote currency and minor-unit semantics;
- each side's MoneyContext availability state, sourced city/national price scopes and payment guidance.

The comparison does **not** compute a winner, universal cost-of-living index, purchasing-power parity claim or direct cross-currency price ratio.

If one side lacks one or more requested budget categories, the result is partial and keeps the known lines visible while preserving the missing-category state. City/national scope and provenance remain properties of each budget line rather than being flattened into a single comparable number.

The current comparison basis is the reference conversion only. Payment-estimate comparison remains future work until the same explicit fee assumptions can be carried transparently and consistently across both destinations.

## SameAmountDestinationSnapshot

Same Amount Across Destinations is a descriptive multi-destination view over canonical current conversion and MoneyContext outputs, not a new financial model.

For each of two to four explicit destination scopes it preserves:

- the trusted ConversionResult;
- provider/effective-date/stale semantics;
- destination currency and canonical country/city identity;
- MoneyContext availability and city/national scope;
- provenance-bearing local context.

The aggregate preserves submitted order and may contain both successful and failed destination entries. It has no winner, cost-of-living score, PPP result, affordability band or automatic reordering primitive.

## PaymentEstimate

A payment estimate is a deterministic scenario calculation layered on top of a trusted current conversion.

Current explicit inputs are:

- non-negative FX markup percentage within the product bound;
- non-negative source-currency fixed fee;
- non-negative destination-currency fixed fee.

The calculation uses Decimal arithmetic and destination-currency minor-unit rounding. Non-negative assumptions must never produce a better destination result than the trusted reference conversion.

It is not a bank/card/ATM quote, does not infer provider fees and is not currently defined for historical payment costs.


## PaymentFeeProfile

A PaymentFeeProfile is an authenticated user's reusable set of **explicit Payment Estimate assumptions** for one exact source/destination currency pair.

It stores only:

- owner;
- bounded display name;
- source currency;
- destination currency;
- FX markup percentage;
- source-currency fixed fee;
- destination-currency fixed fee;
- created/updated timestamps.

The pair must contain two different currencies. Markup is bounded by the same Payment Estimate product limit; fixed fees are non-negative and representation-bounded. Profiles do **not** store an FX quote, payment-provider identity, card/bank/ATM metadata, executable rate, merchant fee claim or conversion result.

Profile application is owner-scoped and exact-pair scoped. A profile may populate the explicit Payment Estimate assumptions only after the current signed conversion snapshot establishes the matching pair. It cannot modify the signed reference conversion.

Profile writes serialize per owner and the first slice limits each account to 12 profiles. Saving an existing exact name is an explicit update rather than an unbounded duplicate.


## CulturalProfile / destination context

Curated current destination guidance such as:

- cash/card usage;
- ATM guidance;
- tipping/customs.

It is current context unless an explicit historical dataset says otherwise.

## TypicalPrice

A scoped price observation used to give rough everyday-value intuition.

Important meaning includes:

- city/national scope;
- canonical `City` relationship for published city-scoped observations;
- legacy city display text retained only for migration/unpublished compatibility;
- normalized category/unit semantics (`coffee→serving`, `casual_meal→meal`, `transit→ride`, `groceries→basket`, `other→item`);
- positive ordered range/value;
- the country's current primary currency for published current-context data;
- observation date within the shared freshness policy;
- source name and credential-free HTTPS provenance;
- explicit verification;
- duplicate identity scoped by canonical destination, category, unit, normalized label and observation date;
- confidence/trust class.

A typical price is an example, not a universal price for a country. Published city observations must satisfy the reusable city-price quality contract; stale or otherwise invalid records are not promoted into current destination context.

City coverage health is a derived maintenance view, not a persisted domain entity. For each active canonical city it reports the current primary currency, currently usable fresh city categories, stale city categories, fresh national fallback categories and provenance gaps. `total_supported_categories` means categories currently usable by runtime city context (fresh city evidence plus fresh national fallback). The diagnostic `coverage_score` uses only the four core maintenance categories and must never be exposed as affordability, value, cost-of-living or destination quality.

When a city is explicitly requested, city-scoped observations take priority and only clearly national observations may fill missing categories. Data from another city must never be substituted silently. National fallback remains visibly labelled as a national estimate.

## Story/cultural facts

Published story facts/moments are reviewed factual content with provenance and temporal scope where needed.

A deterministic composer can create user-facing stories from those facts.

## MediaAsset

Managed media represents a reviewed media candidate/asset with:

- role;
- source/creator/licence/provenance;
- optional country/currency/time association;
- stored file/derivatives;
- publication state.

Large editorial imagery comes from reviewed managed raster assets. Missing media is a valid state; country/editorial surfaces do not require a decorative static-image fallback.

## FavouritePair

A saved semantic source/destination pair owned either by local browser state or a signed-in account, depending on the persistence mode.

Account-owned records should be scoped to the authenticated owner.

## RecentConversion

A bounded record of a successful conversion used for repeat convenience.

Browser-local recents and account recents are intentionally distinct privacy surfaces.

Account recent history is only recorded after explicit opt-in and does not silently import existing local browser history.

## SavedPlace / browser-local My Places

My Places has two intentionally separate persistence modes.

**Browser-local My Places** stores validated, versioned and retention-bounded convenience records containing country/city labels, canonical country/city identity, current currency shortcut metadata and save time. This state remains device-local and is never uploaded merely because the user signs in.

**Account-owned SavedPlace** stores only:

- authenticated owner;
- canonical country;
- optional canonical city;
- created/updated timestamps.

The account model intentionally does **not** persist a current currency snapshot. Canonical re-entry resolves the country's current primary currency again at read time, so a later currency transition cannot turn an old shortcut into stale financial truth. Country-level and city-level duplicates are prevented per owner. City/country coherence is validated before supported writes.

Local→account migration is explicit and idempotent. The browser posts only canonical country/city identities; the server validates all requested scopes before any write, unions them with existing owner records, and the browser removes confirmed local copies only after account commit succeeds. If local cleanup fails after the server commit, the account records remain valid and the browser copies are retained for safe manual cleanup.

## SavedComparison

A SavedComparison is an owner-scoped reusable **input contract**, not a persisted comparison result.

It stores:

- source amount and source currency;
- canonical left/right country scopes plus optional cities;
- trip duration and traveler count;
- normalized reference-basket category assumptions;
- a deterministic per-owner fingerprint for idempotency.

It does **not** store an FX quote, local-price result, ranking, PPP output or rendered comparison answer. A short-lived signed token is produced only after a successful canonical comparison and carries those same canonical inputs. Saving verifies the token and current canonical identities before persistence.

**Reopen** serializes the saved inputs back into the GET form and performs no provider call. **Re-check** is a separate explicit POST through the canonical Destination Comparison path, so current FX/context truth is recalculated only when the user asks.

## ShoppingEstimate

A ShoppingEstimate is a deterministic **foreign-purchase cost** layered on one trusted current conversion.

The canonical direction is:

```text
purchase currency → home currency
```

The conversion input is exactly the explicit purchase-currency total:

```text
item price + shipping + known fees
```

An optional user-entered FX markup is applied transparently to the trusted reference home-currency cost. It is an assumption, not a bank/issuer fact. Non-negative assumptions may never improve the reference cost.

Duties, taxes and issuer/merchant fees remain unknown unless they are authoritative or explicitly entered as a known fee. The shopping domain does not infer or estimate them silently.

Historical FX and same-currency purchases are outside this foreign-shopping estimate contract. Saved Shopping scenarios reuse `SavedScenario` ownership and immutable FX observations rather than creating a parallel persistence model. Their exact item price, shipping, known fees and FX-markup assumption live in a normalized one-to-one `SavedScenarioShoppingAssumptions` payload; derived home-currency values are recomputed from that payload plus the immutable initial observation.

## SavedScenario

A SavedScenario is a signed-in user's reusable planning state for a **trip**, **budget** or **shopping** workflow.

It is deliberately separate from `FavouritePair` and `RecentConversion`:

- a favourite is a lightweight pair shortcut;
- a recent conversion is bounded history;
- a saved scenario carries explicit planning assumptions that should survive reopening and re-checking.

Current scenario identity includes source/destination currencies, optional source/destination countries, optional canonical destination city, source amount, optional trip dates, explicit duration and traveller count.

Travel timing is explicit planning metadata, not inferred itinerary state. An end date cannot exist without a start date, and when both dates are present the end date cannot precede the start date. This invariant is enforced at form/domain and database boundaries. Date-aware readiness is derived at read time from the configured application-local date and does not mutate the scenario or trigger background work.

Trip and budget scenarios require destination-country context. A destination city must belong to that country. Country/currency associations are validated against the current temporal mapping when the scenario is created.

### SavedScenarioBudgetItem

Budget assumptions are normalized child rows rather than an opaque JSON payload. Each scenario can store at most one assumption per category, expressed as positive units per person per day.

This keeps saved assumptions reusable by the deterministic BudgetInterpretation engine while allowing current price/provenance data to be reloaded on re-open instead of freezing old local-price claims into the scenario.

### SavedScenarioObservation

A scenario observation is an immutable trusted current FX observation recorded when the scenario is first saved or explicitly re-checked.

It stores the scenario amount, output amount, rate, effective date, provider attribution, fetch timestamp and stale state. Historical FX is not accepted into this current travel-scenario path.

Observations are append-only, and an explicit re-check does not add a duplicate row when the latest stored observation already represents the same effective date, rate, output, provider attribution and stale state. A bounded per-scenario observation history prevents accidental/unbounded growth while preserving the original baseline.

The account scenario detail can compare the immutable initial observation with the latest distinct re-check using deterministic Decimal arithmetic. The comparison reports the rate/output difference neutrally and does not attach investment or exchange-timing meaning.

## Camera amount extraction

Camera input has no durable database model in the first slice.

`SanitizedCameraImage` is an ephemeral in-memory value produced only after file-size/type, decoded-pixel and single-frame validation. It is metadata-stripped and normalized before external processing.

`CameraAmountCandidate` contains only:

- positive bounded Decimal amount;
- blank or normalized three-letter currency code;
- semantic kind (`total`, `line_item`, `atm_amount`, `other`);
- bounded confidence class.

A provider response may contain at most six candidates. Empty output is a distinct “no amount found” state; malformed provider data is not accepted as a valid extraction.

A signed camera candidate token binds one normalized candidate to a narrow scenario scope for a short time. User confirmation may correct the amount but cannot silently reinterpret an explicit conflicting currency. The resulting confirmed-camera token contains scope, amount, currency code and a signed unique confirmation id. It is not a spend record and carries no image, merchant, receipt text, account/card field or provider prose. The confirmation id becomes the spend idempotency key only if the user performs the later explicit **Add to trip budget** action.

### SavedScenarioSpendEntry

A spend entry is a minimal immutable record of **confirmed destination-currency spend** for a saved budget scenario.

Current identity is deliberately narrow:

- parent saved budget scenario;
- positive amount representable in the scenario destination currency's minor units;
- confirmation source (`manual` or explicitly user-confirmed `camera`);
- opaque submission idempotency key;
- recorded timestamp.

The model does not store merchant identity, receipt/media bytes, arbitrary purchase notes or an inferred category. Corrections are explicit delete-and-add operations rather than in-place mutation. Replaying one confirmed submission key returns the existing entry instead of recording spend twice.

Scenario creation establishes one `initial` FX observation, and a database uniqueness constraint prevents a second `initial` row for the same scenario. The creation-service contract plus that constraint make the original observation the unique immutable reference-budget baseline used by Trip Budget Remaining.

The original `SavedScenarioObservation(kind=initial)` output amount is the reference-budget baseline. Later re-check observations must not change remaining-budget arithmetic. This keeps **rate movement** and **confirmed spending** as separate meanings.

`TripBudgetSummary` is derived state, not persisted financial truth: confirmed spend is summed, remaining never goes below zero, over-reference is reported separately, and a per-day reference is shown only when explicit duration/date semantics support it.

The first account-facing budget save flow persists only normalized scenario assumptions plus the trusted FX observation. Current TypicalPrice rows and rendered budget results are intentionally **not** copied into the scenario: when the product later re-checks a scenario, current local-price context should be recomputed from the canonical provenance-aware data layer rather than presenting an old local-price snapshot as current truth.

Scenario read/delete operations are always owner-scoped. Anonymous browser-local scenario persistence is a separate future privacy surface and must not be inferred from account persistence.


## OfflineDestinationPack

`OfflineDestinationPack` is derived, versioned export state rather than a database table.

The first format contains:

- scenario/destination identity and optional saved travel timing;
- the newest already-stored FX observation as a stored reference;
- Trip Budget Remaining derived from the immutable initial observation plus confirmed spend;
- destination-context availability state;
- reviewed local-price/payment context captured from the canonical data layer at generation time;
- explicit pack generation time and context as-of date.

The pack is intentionally regenerated rather than persisted server-side. It cannot refresh while offline and therefore never calls itself “current” merely because the original observation was fresh when saved. Local destination-context failure is represented as `degraded`, while saved FX/budget state remains exportable.

The first HTML representation contains no executable script, remote stylesheet or managed-media dependency. Provenance links remain ordinary links and naturally require connectivity if the user chooses to open them.

## Account preferences

Privacy-affecting persistence preferences belong to the account and should have explicit defaults.

## Data provenance

For externally sourced or editorial factual data, provenance is part of the product meaning rather than optional metadata.

The exact schema can evolve, but the UI should be able to communicate enough source/time context to avoid misleading precision.

## Domain invariants worth protecting

Examples of durable invariants:

- country and currency identity remain separate;
- temporal country/currency relationships are explicit and primary eras do not overlap;
- financial arithmetic uses Decimal semantics;
- FX rates must remain within a deliberately generous numeric representation envelope before they can enter cached or presentation-facing domain objects, preventing malformed upstream exponents or precision from expanding responses without bound;
- historical requested date and effective observation date are not silently conflated;
- provider observations cannot be dated after the time they were fetched;
- synthetic exact same-currency identity quotes may bridge at most one calendar-day local/UTC rollover because they are not provider observations;
- cached/provider retrieval timestamps beyond bounded clock skew are rejected rather than treated as fresh;
- latest/reference observations stay within the accepted window for their publication frequency;
- user-facing future-date validation uses the configured application-local calendar date rather than a UTC rollover;
- current context is not silently backdated;
- user-owned data is ownership scoped;
- account recent history requires explicit opt-in;
- sourced factual enrichment keeps provenance;
- optional enrichment cannot invalidate a valid conversion.

These invariants deserve tests. Other implementation details can evolve more freely.
