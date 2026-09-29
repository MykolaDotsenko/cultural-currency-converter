# Domain Model

This document describes the meaning of the main concepts. Field-level details live in Django models and migrations.

## Country

A geographic/political country identity used for travel context.

Important distinction: a country is not a currency.

Typical identity fields include ISO codes and display name.

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
- range/value;
- observation date;
- provenance;
- confidence/trust class.

A typical price is an example, not a universal price for a country.

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
- historical requested date and effective observation date are not silently conflated;
- provider observations cannot be dated after the time they were fetched;
- latest/reference observations stay within the accepted window for their publication frequency;
- current context is not silently backdated;
- user-owned data is ownership scoped;
- account recent history requires explicit opt-in;
- sourced factual enrichment keeps provenance;
- optional enrichment cannot invalidate a valid conversion.

These invariants deserve tests. Other implementation details can evolve more freely.
