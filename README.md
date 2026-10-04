# Cultural Currency Converter

> Convert money. Understand local value. Discover culture.

A Django travel-money application that combines currency conversion with practical destination context: what an amount can roughly buy, how people tend to pay, and where the underlying information came from.

**Live demo:** https://cultural-currency-converter-mykola.onrender.com

The hosted portfolio demo uses ephemeral local persistence; the strict production configuration remains PostgreSQL + Redis.

<p align="center">
  <img src="docs/assets/cultural-currency-converter-overview.webp"
       alt="Cultural Currency Converter desktop interface showing a conversion result and local context"
       width="500">
</p>

## The engineering problem

The arithmetic is the easy part. A useful currency product also has to answer:

- **Which rate was used?** Current and historical conversions keep source and effective-date semantics explicit.
- **What happens when a provider fails?** Core conversion still works if optional media, enrichment or AI is unavailable.
- **Where did local context come from?** Destination content and managed media keep provenance instead of presenting generated filler as fact.
- **Who owns saved data?** Anonymous favourites, recent conversions and My Places stay browser-local. Signed-in favourites, saved scenarios, SavedComparison and My Places are owner-scoped; browser-local My Places move to the account only through an explicit import action.

Those boundaries are more important to this project than adding another conversion widget.

## What works today

- current and historical FX conversion;
- visible source/effective-date meaning;
- bilateral country/currency context with smart current/historical picker filtering;
- historical charts with 1Y / 5Y / 10Y / custom ranges, anchor observations, date-scoped historical evidence and symmetric Then & Now media when reviewed assets exist;
- explicit-assumption Real Payment Estimate for known FX markup and fixed fees, with exact-pair account fee profiles and a signed handoff into payment-adjusted Budget Interpretation;
- foreign-purchase Shopping estimate with explicit item price, shipping, known purchase-currency fees and optional user-entered FX markup, preserving current reference-rate provider/effective-date semantics while leaving unknown duties/taxes/issuer costs explicitly unknown;
- sourced everyday-value and payment context;
- deterministic at-a-glance result summaries that prioritize historical/stale/exact trust semantics and only use reviewed Money Context anchors when available;
- destination-first planning that resolves a country or canonical city into its current primary local currency and reuses the canonical converter/Money Context path;
- deterministic budget interpretation against explicit sourced reference-basket assumptions;
- side-by-side destination comparison for one source budget across two explicit country/canonical-city scopes, preserving each side's rate source/date, local-price provenance and payment context without ranking destinations;
- account-owned saved budget scenarios with optional travel dates, immutable FX observations, explicit reference-rate re-check, neutral since-saved comparison, date-aware trip readiness, confirmed-spend tracking, deterministic remaining-budget meaning and an explicit current local-money-guide refresh that never mutates saved FX evidence;
- returning-user home continuity for the most relevant active/upcoming saved trip, using stored FX observations, confirmed spend and reviewed local-context freshness without silent rate refresh;
- optional, explicitly enabled camera amount extraction for saved budget scenarios with ephemeral metadata-stripped image processing, mandatory user confirmation and a separate idempotent Add-to-trip-budget handoff;
- self-contained offline destination-pack export using stored FX/freshness semantics and reviewed destination context;
- provider-free regional Explore discovery over reviewed country/canonical-city money context, with five provenance-bearing collections, region → country → city navigation, curated country teaser media and canonical Converter/City Profile handoffs;
- Same Amount Across Destinations for two to four explicit destinations, preserving independent rate/provider/date/scope/provenance semantics without ranking, PPP or affordability claims;
- canonical one-sided Compare handoffs from Explore, My Places, saved scenarios, favourites and recent conversions; Destination B is never inferred;
- durable My Places with owner-scoped canonical country/city identity, current-currency re-resolution, explicit browser-local → account import and Saved-page continuity into Convert, Budget, Compare and City Profile;
- owner-scoped SavedComparison persistence that stores only canonical inputs/explicit basket assumptions; Reopen is provider-free and Re-check returns through the canonical comparison POST path;
- provider-free City Money Profile pages with direct-city evidence requirements, explicit city/national scope, reviewed price/payment context, provenance and managed social-preview metadata when available;
- read-only `report_city_coverage` maintenance diagnostics for reviewed city-price freshness, national fallback and provenance gaps; its score is operational only, never a cost-of-living ranking;
- Historical Series chronology with factual range landmarks, date-scoped historical-timeline media and symmetric Then & Now imagery, plus Money & culture currency-era / reviewed-story exploration with chapter-scoped sourced media and publication/retrieval/review provenance while keeping historical FX separate from historical purchasing power;
- restrained source → destination result identity and provenance-aware managed media with graceful no-media rendering, public-safe creator/rights/retrieval/original-source disclosure, human-readable authenticity/temporal-match labels, managed social previews, plus sourced Finland/Japan/France P01–P04 showcase manifests with reviewed focal points, responsive-width plans, idempotent derivative generation and strict deployment-readiness reporting;
- optional Gemini structured insight with deterministic fallback, server-approved contextual quick prompts and per-section grounding against trusted structured packets; Explore AI is an explicit POST over a reviewed destination/intent while Explore GET remains provider-free;
- demand-loaded converter/picker, saved-state and rate-chart enhancements with HTMX re-discovery and browser route-isolation checks;
- browser-local anonymous favourites and recent conversions, signed-in favourite ownership and opt-in cross-device history.

## Architecture

```text
Browser
  ↓
Django templates + HTMX + small TypeScript enhancements
  ↓
Application / use-case layer
  ↓
Domain rules
  ↓
Django ORM / cache / provider adapters
  ↓
PostgreSQL or SQLite (local) + external data providers
```

The provider boundary keeps external payloads out of the rest of the application. Domain/application code works with normalized data instead of depending directly on a third-party response shape.

## Stack

- **Backend:** Python 3.13/3.14, Django 5.2
- **UI:** Django templates, HTMX 2, TypeScript, Vite 8, Tailwind 4
- **Data:** PostgreSQL in production-oriented environments; SQLite for lightweight local development
- **FX provider:** Frankfurter
- **Optional AI:** Gemini behind server-side configuration, with validated structured output, deterministic fallback and signed grounded packets for post-result Budget/Comparison explanations
- **Quality:** pytest/Django tests, coverage, Ruff, mypy, djlint, Playwright and axe

## Quality checks

Backend:

```bash
ruff format --check apps config scripts manage.py
ruff check apps config scripts manage.py
djlint templates --check
python manage.py check
python manage.py makemigrations --check --dry-run
coverage run -m pytest -q
coverage report
```

Frontend/browser:

```bash
cd frontend
npm run quality
npm run browser:quality
```

The Python test suite is configured with a **90% minimum coverage gate**.

## Local development

```bash
python -m pip install -e ".[dev]"
python manage.py migrate
python manage.py seed_reference_data
python manage.py seed_story_data
python manage.py seed_destination_context
python manage.py runserver
```

Frontend tooling:

```bash
cd frontend
npm ci
npm run dev
```

## Documentation

Start with [docs/00_INDEX.md](docs/00_INDEX.md) for product intent, architecture, integrations and current constraints.

Development workflow: [CONTRIBUTING.md](CONTRIBUTING.md)

AI-assisted changes have an additional repository-specific guide at [docs/AI_DEVELOPMENT_GUIDE.md](docs/AI_DEVELOPMENT_GUIDE.md); it is development process documentation, not part of the runtime product architecture.

## Scope

The current product is the Django web application described above. Mobile/API work is a possible future direction, not a shipped capability.
