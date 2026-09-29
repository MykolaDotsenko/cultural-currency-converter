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
- wire selected photography into the most valuable destination/context surfaces;
- keep the converter clean when photography is unavailable;
- establish consistent image crops, focal points and tonal treatment;
- prefer authentic archival/heritage media in historical experiences;
- remove remaining visual patterns that feel demo-like or decorative;
- simplify UX where controls/content are duplicated;
- improve empty/degraded states;
- profile product performance with real photographic media;
- improve portfolio/demo clarity.

Do not add images simply to increase visual density.

## Next candidate: stable external/mobile API

A versioned API is useful when a native client or external consumer becomes active.

Before implementation, re-evaluate framework/schema/authentication/offline choices against the then-current product.

## Later candidate: native mobile

A native client should reuse backend/domain meaning rather than duplicate web business rules.

Choose the current stable mobile stack when implementation starts.

## Later candidate: trips and budgets

Trip/budget workflows may become valuable after the core converter/context experience demonstrates repeat use.

## Research: historical purchasing power

Historical FX and historical purchasing power are different questions. Shipping purchasing-power claims requires defensible datasets, methodology, provenance and uncertainty communication.

## Production hardening

PostgreSQL backup/clean-restore recovery and runtime observability now have executable CI evidence.

As public usage grows, continue with deployment-specific backup scheduling/retention and measured RPO/RTO, provider-incident drills, and media/object-storage durability. Deterministic frontend/query performance budgets now have a measured CI baseline; real-user timing thresholds remain a future evidence task. Security headers remain part of the tested deployment baseline.

## How to add roadmap work

Add work when it has a user outcome, enough evidence to justify it and a rough dependency/risk picture.

Use issues/PRs for implementation detail rather than creating another parallel roadmap document.
