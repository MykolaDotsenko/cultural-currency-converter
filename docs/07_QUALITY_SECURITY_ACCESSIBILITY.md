# Engineering Quality, Security and Accessibility

This document describes the practical quality baseline. CI/config files are the executable source for exact versions, thresholds and commands.

## Development principle

Use the smallest set of checks that gives confidence for the change, then run broader checks before merging when risk warrants it.

Do not add process for its own sake.

## Python/Django checks

The current CI runs checks equivalent to:

```bash
ruff format --check apps config scripts manage.py
ruff check apps config scripts manage.py
mypy apps/exchange/domain.py apps/exchange/providers/base.py apps/exchange/providers/frankfurter.py config/environment.py config/database.py config/cache.py config/csp.py config/ai.py integrations/gemini/client.py
djlint templates --check
python manage.py check
python manage.py makemigrations --check --dry-run
coverage run -m pytest -q
coverage report
python -m pip_audit --skip-editable
```

The coverage threshold and source packages are configured in `pyproject.toml`; treat that file as authoritative. Coverage includes application, configuration and integration code. Static typing is intentionally introduced first at the financial/provider/config boundaries rather than pretending the entire Django surface is strict-typed.

PostgreSQL also has a dedicated CI job because SQLite alone cannot validate all persistence/concurrency behaviour.

## Frontend checks

```bash
cd frontend
npm ci
npm run typecheck
npm run check
npm run build
```

Browser QA uses Playwright and axe. Chromium carries the broadest gate; Firefox/WebKit provide smoke coverage.

Use browser tests for high-value interaction behaviour, not every CSS detail.

## Testing priorities

Prefer tests that protect:

- financial/domain semantics;
- historical date semantics;
- ownership/privacy boundaries;
- external-provider normalization and failure handling;
- important form/HTMX flows;
- accessibility behaviour;
- migrations/constraints where data can be corrupted;
- regressions that have actually occurred.

Avoid duplicating the implementation structure in tests when no user/domain risk is protected.

## Security baseline

Deployed HTTPS policy is explicit rather than inferred. Preview and production must declare whether Django receives HTTPS directly or trusts a TLS-terminating proxy. Production also requires a positive HSTS window; increase it gradually only after the real HTTPS topology is verified. Proxy mode trusts `X-Forwarded-Proto`, so it must only be used behind a proxy that overwrites that header rather than accepting it from arbitrary clients.

CI boots production-like settings against PostgreSQL and runs `python manage.py check --deploy --fail-level WARNING`, then asserts the secure redirect/proxy/HSTS/cookie settings. This keeps deployment assumptions executable.

The public web surface also uses an explicit Content Security Policy. Test/browser QA runs with enforcement enabled so HTMX/Vite interactions are exercised under the real policy, including a negative browser check that injected inline script does not execute. HTMX's built-in indicator-style injection is disabled; the equivalent indicator rules are owned by the external Vite stylesheet so strict `style-src` remains enforceable. Preview and production must explicitly choose `DJANGO_CSP_MODE=report-only` or `enforce`; production-like CI verifies the enforced header. The public policy allows scripts only from the same origin, forbids inline script attributes, `unsafe-eval`, objects and framing, and limits dynamic media presentation styles (currently aspect ratio and reviewed focal-position cropping) to `style-src-attr`. Django admin uses a separate compatibility policy because its upstream templates may require inline assets; that exception is not applied to public pages.

CSP violation reports are accepted by a bounded same-origin endpoint. The endpoint does not persist document URLs/query strings and logs only the directive, disposition and a sanitized blocked-resource origin/category.

Keep:

- secrets server-side and out of version control;
- CSRF protection on state-changing browser requests;
- secure cookie/settings behaviour in production;
- strict host/config validation;
- sanitized external URLs/media;
- redaction for credential-bearing logs;
- dependency audits.

Do not weaken Django defaults without a concrete reason and test.

## Privacy and ownership

User-owned database rows should be queried/mutated through the authenticated owner boundary.

Cross-device recent history is opt-in. Disabling future recording should not unexpectedly delete existing history unless the user explicitly chooses deletion.

Anonymous browser state should be described as local browser storage, not account sync.

## Accessibility baseline

Target WCAG 2.2 AA behaviour for the product experience.

Important practical checks include:

- keyboard-only operation;
- visible focus;
- correct labels/descriptions/errors;
- sensible heading/landmark structure;
- no colour-only meaning;
- reflow/zoom resilience;
- reduced-motion support;
- meaningful live announcements without duplicate noise;
- usable touch targets.

Automated axe checks are useful but do not replace interaction testing.

## Configuration

Runtime configuration is validated in `config/environment.py`, `config/database.py`, `config/cache.py`, `config/storage.py`, `config/csp.py` and `config/ai.py`.

Preview and production require an explicit shared `CACHE_URL`; local/test execution may omit it and use process-local memory caching. PostgreSQL CI also exercises a real Redis service so the deployed cache backend is tested rather than only configuration-parsed.

Use `.env.example` as the practical inventory of supported environment variables.

Avoid duplicating exact default values in documentation when the code is clearer and already tested.

## Database changes

For schema/data changes:

1. make the smallest migration that preserves data;
2. use constraints when an invariant belongs in the database;
3. test risky backfills/destructive changes;
4. prefer additive/expand-first changes when rollback compatibility matters;
5. do not hide destructive operations inside unrelated migrations.

For imports/seeds, favour idempotent behaviour and explicit provenance.

## Release/rollback and database recovery

Before a release, consider:

- migrations;
- configuration/secrets;
- static build;
- provider dependencies;
- smoke paths;
- rollback/roll-forward options.

Prefer roll-forward for simple defects once migrations/data are already in use. Do not assume database rollback is safe.

PostgreSQL recovery uses native custom-format `pg_dump`/`pg_restore` archives:

- `scripts/postgres_backup.sh` writes a private-permission custom archive plus a SHA-256 sidecar and validates that `pg_restore` can list the archive;
- existing archive/checksum paths are not overwritten unless `BACKUP_OVERWRITE=true` is explicit;
- `scripts/postgres_restore.sh` requires `RESTORE_CONFIRM=restore-empty-database`, verifies the exact archive checksum and refuses a target containing user tables/views/sequences;
- restore uses `--single-transaction --exit-on-error` and does not perform an in-place `--clean` against a live database.

Operationally, restore into a fresh database, run Django checks/migration checks and application smoke verification, then cut the application over to the recovered database. Keep the old database available until recovery confidence is established.

Supply credential-bearing database URLs through environment/secrets rather than embedding them in scripts or logs. Prefer a PostgreSQL client version matching the server major version; CI proves the path with the pinned PostgreSQL image used by the project.

The required PostgreSQL CI lane performs a real recovery drill: deterministic reference data is backed up, restored into a new empty database, migration state is checked and restored FI/EUR data is queried. It also proves that backup overwrite and non-empty restore guards reject unsafe repetition.

This database procedure protects PostgreSQL data only. Production now refuses ephemeral filesystem media storage and requires the configured S3-compatible backend, but the object store still needs deployment-specific versioning/retention/backup policy in addition to restoring database metadata.

Do not claim a production RPO or RTO from CI alone. Set backup frequency/retention off-platform, then measure real backup age and restore duration in the chosen deployment.

## Runtime health and operational telemetry

Keep the health endpoints semantically narrow:

- `/health/live/` is process liveness and must not touch PostgreSQL, Redis or external providers;
- `/health/ready/` verifies PostgreSQL because durable application state cannot be served safely without it;
- when a deployed shared cache is unavailable, readiness remains HTTP 200 with `status=degraded`; FX/cache and AI coordination paths are designed to fail open;
- optional runtime AI explanation persistence also fails open: database read/write/cleanup failures are logged, while the user still receives either a live uncached explanation or the deterministic fallback;
- external FX/AI providers are observed through real request telemetry, not synthetic health probes.

PostgreSQL CI runs the readiness endpoint against real PostgreSQL and Redis so this contract remains executable.

Structured operational events should expose only bounded fields needed for diagnosis/aggregation. Current provider signals include operation, outcome, attempts and latency; AI signals also expose model and token counts. Stale FX fallback is logged explicitly as a degraded-but-successful path. Do not add raw provider URLs, query parameters, payloads, user conversion values or AI packet hashes to routine telemetry.

## Performance

Performance work is evidence-driven. Deterministic growth budgets are merge gates; noisy lab timings remain recorded evidence until the CI environment can support a stable threshold.

The 2026-09-25 Chromium/production-build baseline measured:

- core application JavaScript: 24,062 B gzip;
- saved-state lazy chunk: 2,144 B gzip;
- historical chart lazy chunk: 54,084 B gzip;
- all JavaScript: 80,290 B gzip;
- application stylesheet: about 13.05 KiB gzip;
- normal initial pages: 4 requests; lazy-chunk pages: 5 requests.

Current hard budgets intentionally leave measured headroom rather than preserving accidental size:

- core JavaScript: <= 32 KiB gzip;
- all JavaScript: <= 96 KiB gzip;
- CSS: <= 16 KiB gzip;
- chart chunk: <= 64 KiB gzip;
- saved-state chunk: <= 8 KiB gzip;
- initial browser surface: <= 5 requests;
- initial converter render: <= 6 SQL queries;
- story composition with a reviewed fact remains <= 4 SQL queries.

The hard initial-request budget measures application page resources and excludes browser-initiated `/favicon.ico` discovery, which differs across browser engines. Browser QA still records the raw browser request count separately for diagnosis.

`npm run quality` enforces production-build asset budgets without starting a browser. Full browser QA reuses the same budget definitions, verifies lazy-route loading and records per-surface request/body/navigation evidence.

`domContentLoaded` and `load` timings are retained in browser artifacts for trend investigation but are not merge gates because shared CI-runner scheduling/network noise can move them without a product regression. Promote a timing metric to a hard gate only after repeated evidence shows a stable test method.

Watch:

- avoidable provider calls;
- N+1 ORM patterns;
- oversized frontend bundles;
- unnecessary eager chart/media code;
- large images;
- slow request-path enrichment.

Use profiling/measurements before introducing caches or infrastructure. When a budget needs to grow, update the code and this rationale together rather than silently widening the threshold.

## Documentation quality

A change should update documentation when it changes stable product meaning, architecture ownership or an external contract.

Do not require documentation edits for every refactor.

## Merge confidence

Pull requests have an always-present `Required merge quality` status. It classifies changed paths, runs the applicable Python/PostgreSQL/frontend/Chromium lanes and fails unless every applicable lane succeeds. This status is designed to be the single required branch-protection check so documentation-only pull requests still receive a deterministic merge result instead of waiting on path-filtered workflows that never start.

The broader Python 3.14 and Firefox/WebKit workflows remain valuable compatibility evidence in addition to that minimum protected merge gate.

A change is generally ready when:

- the user/problem outcome is satisfied;
- relevant tests pass;
- failure/security/privacy/accessibility risks are covered proportionally;
- migrations/config changes are explicit;
- docs remain aligned where the project meaning changed.
