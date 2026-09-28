# Cultural Currency Converter

> Convert money. Understand local value. Discover culture.

A Django travel-money application that combines currency conversion with practical destination context: what an amount can roughly buy, how people tend to pay, and where the underlying information came from.

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
- **Who owns saved data?** Anonymous favourites/recent conversions stay browser-local; signed-in data is owner-scoped and cross-device history is opt-in.

Those boundaries are more important to this project than adding another conversion widget.

## What works today

- current and historical FX conversion;
- visible source/effective-date meaning;
- bilateral country/currency context;
- historical charts and Then & Now comparison;
- sourced everyday-value and payment context;
- deterministic Money & culture stories;
- provenance-aware photographic media;
- optional Gemini explanation with deterministic fallback;
- browser-local anonymous favourites and recent conversions;
- signed-in favourite ownership and opt-in cross-device history.

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
- **Optional AI:** Gemini, behind server-side configuration
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
