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
mypy apps/culture/price_quality.py apps/culture/city_health.py apps/exchange/domain.py apps/exchange/budget.py apps/exchange/comparison.py apps/exchange/money_context.py apps/exchange/payment_estimate.py apps/exchange/result_summary.py apps/exchange/providers/base.py apps/exchange/providers/frankfurter.py apps/travel/scenarios.py config/environment.py config/database.py config/cache.py config/csp.py config/ai.py integrations/gemini/client.py
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
npm run quality
```

`npm run quality` includes TypeScript checking, Biome, the CSS custom-property integrity contract, the production build and deterministic asset-budget checks.

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

## Production acceptance matrix

The production-readiness program uses this matrix as an **index of evidence**, not as a second test suite. The implementation and tests remain authoritative. When a listed test moves or a risk dimension changes, update this matrix in the same PR so release readiness stays auditable.

### Risk-dimension legend

- **H — happy path:** the intended successful user outcome works.
- **E — empty state:** zero-data or not-yet-used state is intentional.
- **I — invalid input:** invalid, ambiguous or out-of-scope input fails safely and preserves useful state.
- **P — partial data:** incomplete optional context stays explicit rather than being guessed.
- **S — stale data:** freshness/effective-date meaning remains visible and stale data cannot masquerade as current.
- **F — required-provider failure:** a dependency required for the requested result fails with a neutral recoverable state.
- **O — optional-system failure:** optional context/media/AI failure does not invalidate financial truth.
- **A — auth/ownership:** account-owned state is inaccessible across owners and anonymous boundaries remain explicit.
- **D — duplicate/idempotency:** retried or replayed writes cannot silently duplicate durable state.
- **K — keyboard:** the primary interaction is operable without a pointing device.
- **X — automated accessibility:** axe/semantic checks cover the rendered surface where browser coverage exists.
- **R — reflow:** narrow/mobile rendering has no horizontal overflow and preserves semantic order.
- **N — no-JavaScript:** the workflow remains usable without JavaScript where the product contract requires a server fallback.
- **C — Chromium:** required Chromium evidence exists.
- **FF — Firefox:** dedicated or smoke Firefox evidence exists.
- **W — WebKit:** dedicated or smoke WebKit evidence exists.
- **PG — PostgreSQL:** persistence/domain behaviour is exercised in the PostgreSQL CI lane when applicable.

A dimension omitted from a row is not silently waived. It is either not meaningful for that surface or belongs to a cross-cutting gate below. If that changes, add the dimension before shipping the behaviour.

### Product-surface evidence

| Surface | Required dimensions | Primary automated evidence | Browser evidence | Current release-readiness note |
| --- | --- | --- | --- | --- |
| Current converter | H E I S F O K X R N C FF W PG | `apps/exchange/tests/test_web.py`, `test_forms.py`, `test_application.py`, `test_frankfurter.py`, `test_cache.py` | `current-converter` is full Chromium + Firefox/WebKit smoke; full flow is exercised on the wide surface | Strong baseline. Final certification still re-runs provider-failure and constrained-network evidence. |
| Historical conversion + rate series | H E I S F K X R C FF W PG | `apps/exchange/tests/test_domain.py`, `test_series.py`, `test_series_presentation.py`, `test_web.py`, `apps/media/tests/test_services.py`, `test_presentation.py` | `rate-series` is full Chromium + Firefox/WebKit smoke | Strong baseline; historical FX/purchasing-power wording remains a permanent semantic audit item. Reviewed Then/Now/timeline media are optional, independently sourced and cannot change FX truth; historical-evidence roles reject generated imagery and require explicit temporal scope/precision. |
| Real Payment Estimate | H I O K X R N C PG | `apps/exchange/tests/test_payment_estimate.py`, `test_payment_estimate_web.py`, `test_fee_profiles.py` | exercised inside the full `current-converter` browser flow | Signed reference semantics, explicit assumption validation and owner/exact-pair reusable fee-profile persistence are covered; saved profiles never carry an FX quote or provider identity. |
| Destination context / local value / culture | H E P S O K X R C FF W PG | `apps/culture/tests/test_destination_context.py`, `test_city_fallback_trust.py`, `test_city_profile.py`, `test_explore_collections.py`, `test_explore_navigation.py`, `test_price_quality.py`, `test_city_health.py`, `test_migrations.py`, `test_destination_empty_state.py`, `test_destination_media.py`, `test_story.py`, `test_web.py`, `test_provenance.py`, `apps/media/tests/test_services.py`, `test_presentation.py`, `test_curated_ingestion.py`, `test_curated_derivatives.py` | rendered through current converter; Explore, provenance-aware Explore collections, canonical regional navigation and City Money Profile carry context evidence; `report_city_coverage` and `report_curated_media_coverage` provide read-only ops evidence | City-price quality has stable issue codes and fail-closed city/national provenance rules. Story chapters support date-scoped sourced evidence and progressive source-review metadata; curated Explore teasers and City/Explore/Story social-preview media remain optional and fail open. Deep media provenance exposes only public-safe creator/rights/retrieval/original-source fields while internal selector mechanics stay hidden. |
| Budget Interpretation / presets | H E I P S O K X R N C PG | `apps/exchange/tests/test_budget.py`, `test_budget_snapshot.py`, `test_budget_web.py`, `test_budget_presets.py` | explicit reference-budget, Payment Estimate → Budget handoff and authenticated preset save/apply inside full `current-converter` QA | Deterministic calculation, insufficient-data semantics, signed planning-context preservation, owner-scoped reusable assumption presets and durable SavedScenario continuity are covered. Presets never carry destination, FX or price evidence. |
| Destination Mode | H E I P K X R N C FF W PG | `apps/exchange/tests/test_destination_mode.py` | dedicated `destination-mode` surface in full Chromium plus Firefox/WebKit smoke at wide/mobile viewports | Cross-engine navigation, form semantics, reflow and accessibility now participate in the normal browser gate. |
| Destination Comparison + SavedComparison continuity | H E I P S F O A D K X R N C FF W PG | `apps/exchange/tests/test_comparison.py`, `test_comparison_web.py`, `test_comparison_snapshot.py`, `apps/travel/tests/test_personalization.py` | dedicated full Chromium + Firefox/WebKit smoke surface; Saved page exercises reopen/re-check actions | Canonical comparison remains the only calculation path. Signed save tokens carry inputs only; Reopen is provider-free; explicit Re-check recomputes through canonical POST; owner isolation/idempotency are persistence requirements. |
| Explore | H E P S O K X R C FF W PG | `apps/culture/tests/test_explore.py`, `test_explore_collections.py`, `test_explore_navigation.py` | dedicated full Chromium + Firefox/WebKit smoke surface | Current provider-free GET covers reviewed collections plus canonical regional navigation. The same surface also exercises the explicit reviewed-destination contextual-AI POST while preserving deterministic GET behavior and provenance boundaries. |
| Smart result summary | H E P S O K X R C FF W PG | `apps/exchange/tests/test_result_summary.py`, `test_web.py` | rendered inside the canonical conversion result; full Chromium + Firefox/WebKit converter flows retain it | Deterministic trust-first summary only. Historical/stale/exact semantics outrank enrichment; reviewed price/payment context is optional; unknown/zero purchase-equivalent states fail closed; no AI, ranking, affordability or exchange-timing recommendation. |
| Optional AI explanation / quick prompts / structured insight | H I F O K X R N C FF W PG | `apps/exchange/tests/test_ai_service.py`, `test_ai_validation.py`, `test_ai_web.py`, `test_ai_intents.py`, `test_ai_deterministic_fixture.py`, `test_ai_eval.py`, `test_ai_tokens.py`, `test_ai_packet_tokens.py`, `test_budget_web.py`, `test_comparison_web.py`, `apps/culture/tests/test_explore.py` | current converter browser QA exercises loading, latest-request-wins cancellation, timeout fallback/retry, focus and live-region semantics through a test-only deterministic drafter in Chromium and smoke engines; Explore uses rebuilt reviewed context; Budget and Comparison expose independent signed-result explanation regions | Conversion/Explore/ Budget/Comparison prompts are bounded and grounded against application-owned structured facts. Budget and Comparison sign the complete packet plus capability after deterministic calculation; explanation POSTs cannot trigger another FX calculation. Capability crossover/tampering, unknown numbers/dates/currencies/facts and positive destination-ranking/affordability language fail closed. Structured insight and deterministic fallback share one validation path. Production rejects the browser AI fixture outside `APP_ENV=test`; live Gemini remains absent from CI. AI stays optional and cannot become factual financial truth. |
| Saved & recent / My Places | H E I A D K X R N C FF W PG | `apps/travel/tests/test_favourites.py`, `test_recent_history.py`, `test_personalization.py`, `test_web.py` | dedicated `saved-state` full Chromium + Firefox/WebKit smoke; corrupt local state is exercised | Anonymous places remain browser-local. Account SavedPlace is owner-scoped and identity-only; local→account migration is explicit/idempotent and preserves local copies if cleanup fails after server commit. Signed-in no-JS place save uses the same canonical service. |
| Account auth + opt-in recent history | H E I A D K X R C PG | `apps/accounts/tests/test_web.py`, `apps/travel/tests/test_recent_history.py` | login/signup surfaces in full Chromium; account-history end-to-end runs from signup in Chromium | Firefox/WebKit do not currently execute the authenticated account-history mutation loop. |
| Saved budget scenario detail / re-check / local guide | H E I P S F O A D K X R C PG | `apps/travel/tests/test_scenarios.py`, `test_scenario_web.py`, `test_scenario_schedule.py`, `test_scenario_comparison.py` | authenticated save/detail flow is exercised in Chromium, including explicit current local-context refresh | Detail GET performs no current-context lookup by default. Explicit refresh reuses reviewed DestinationContext, persists nothing, degrades locally and must not change immutable FX history or Trip Budget Remaining. Dedicated cross-engine authenticated mutation coverage remains a final-certification decision. |
| Scenario notifications | H E I S O A D K X R C PG | `apps/travel/tests/test_notification_preferences.py`, `test_notification_delivery.py` | authenticated Chromium trip E2E saves an explicit rate-alert threshold, verifies persistence, opens the in-app inbox and runs axe on configuration/inbox surfaces | Preferences are explicit and owner-scoped. Due generation covers pre-trip, conservative freshness and rate-alert paths; cadence is timezone-aware, stale/provider-failed probes fail closed, transient rate probes do not mutate scenario observation history, and database dedupe makes scheduler retries idempotent. |
| Trip Budget Remaining | H E I A D K X R C PG | `apps/travel/tests/test_trip_budget.py`, `test_trip_budget_web.py`, `test_scenarios.py` | add/remove/remaining-budget flow is exercised in authenticated Chromium end-to-end QA | Idempotency and immutable-baseline semantics are release-critical. |
| Returning-user Trip Home | H E P S O A K X R C PG | `apps/travel/tests/test_home.py` | authenticated Chromium end-to-end returns to clean home and verifies saved-trip continuity | No live rate refresh is a trust invariant. Dedicated Firefox/WebKit auth coverage is not current. |
| Camera extraction + confirmation + spend handoff | H E I F O A D K X R C PG | `apps/exchange/tests/test_camera.py`, `test_camera_service.py`, `test_camera_gemini_provider.py`, `apps/travel/tests/test_camera_web.py` | authenticated full-Chromium trip E2E uploads a real PNG through the test-only deterministic extractor, confirms the signed candidate, performs the separate spend POST and runs axe on candidate/confirmed states | Raw media still passes the production sanitizer and is never persisted. The deterministic Camera fixture is rejected outside `APP_ENV=test`, so browser evidence does not create a production bypass. |
| Offline Destination Pack | H E P S O A D K X R C PG | `apps/travel/tests/test_offline_pack_web.py` | authenticated full-Chromium trip E2E downloads the real attachment, verifies filename/freshness/self-contained markup, opens the downloaded HTML without network dependencies and runs overflow/axe checks | Offline means stored, not live: the pack carries saved FX/context freshness semantics and no script or external stylesheet dependency. |

### Cross-cutting gates

These checks apply across surfaces and should not be copied into every row:

| Gate | Executable evidence | Acceptance meaning |
| --- | --- | --- |
| Python/Django | `.github/workflows/required-merge-quality.yml`, `.github/workflows/django-tests.yml` | Ruff, mypy on typed boundaries, Django checks, migrations check, pytest/coverage and dependency audit remain green. |
| PostgreSQL + Redis | required PostgreSQL lane | real PostgreSQL persistence, shared Redis behaviour, readiness semantics, migrations and full pytest suite pass. |
| Backup/restore | required PostgreSQL lane + `scripts/postgres_backup.sh` / `scripts/postgres_restore.sh` | backup checksum/overwrite guards and clean-database restore are executable; deployment-specific RPO/RTO remains a later production-evidence requirement. |
| Browser engines | `.github/workflows/browser-quality.yml` | Chromium runs full scope across wide, breakpoint-transition, 430/390/360 mobile and 640/320 reflow viewports. Firefox/WebKit run smoke on current converter, Destination Mode, comparison, Explore, City Money Profile, Money & culture, saved state and rate series at wide/390px mobile viewports. Browser/release-quality runs enable the test-only deterministic FX provider so engine evidence is not coupled to public-provider network availability; Frankfurter transport/normalization remains covered separately by provider tests. |
| Accessibility/reflow | `frontend/scripts/browser-quality.mjs` | axe, keyboard focus, overflow, reduced motion and forced colors run according to browser scope. Full Chromium now includes page-level 430/390/360/320 mobile regression coverage and separately certifies 640px and 320px reflow surfaces (roughly 200% and 400% zoom equivalents from a 1280px reference viewport) with 200% text expansion and no horizontal page scrolling. |
| No-JavaScript | `frontend/scripts/browser-quality.mjs` + server web tests | workflows that promise a server fallback must not become inert when enhancement is absent. |
| CSP/deploy security | required PostgreSQL lane + browser CSP enforcement check | production settings, secure cookies/HSTS/proxy assumptions and public CSP remain executable. |
| Performance | `frontend/scripts/performance-budgets.mjs`, frontend quality, browser quality, curated media derivative/readiness tests | JS/CSS/request/query budgets may grow only with measured justification. Destination photography uses reviewed responsive width families rather than full-size source delivery; one derivative per source/width is enforced in the database, source/derivative provenance and pixel dimensions are re-validated, and runtime readiness is auditable without network access. |
| Constrained network | full Chromium `frontend/scripts/browser-quality.mjs` | a throttled mobile converter flow must still expose the deterministic conversion result, remain overflow-free and pass axe; latency is evidence, not financial truth. |
| Optional dependency failure | provider/service tests + Money Context/AI/Camera tests | optional media/context/AI failures degrade locally and never corrupt conversion or saved financial state. |

### How to use the matrix in a PR

Before merging a meaningful product change:

1. identify every affected surface row;
2. identify every new or changed risk dimension;
3. point the PR tests at the real risk instead of duplicating the implementation;
4. add browser coverage when the interaction cannot be proven safely at the server/domain layer;
5. update the matrix only when a durable acceptance obligation or evidence location changes;
6. do not mark a future release gap as covered merely because a neighbouring surface has a test.

The final 100/100 certification must close every row explicitly marked as a release gap or document why the dimension is no longer applicable.

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

Anonymous browser state should be described as local browser storage, not account sync. Signing in must not silently import browser-local My Places. Supported migration is an explicit user action, and a successful account commit must not be rolled back or misreported merely because later local cleanup fails.

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
- external FX/AI providers are observed through real request telemetry, not synthetic health probes;
- fail-open enrichment boundaries catch explicit dependency/data failures rather than arbitrary programming exceptions, so optional content can degrade without hiding regressions in application code.

PostgreSQL CI runs the readiness endpoint against real PostgreSQL and Redis so this contract remains executable.

The repository-level `render.yaml` is the deployment configuration source of truth for the hosted demo. It pins the existing Render service name, Frankfurt region, build/start commands, application-level `/health/ready/` health check and `checksPass` auto-deploy policy. Dashboard changes should be synchronized back to the Blueprint instead of becoming undocumented service drift.

Structured operational events should expose only bounded fields needed for diagnosis/aggregation. Current provider signals include operation, outcome, attempts and latency; AI signals also expose model and token counts. Stale FX fallback is logged explicitly as a degraded-but-successful path. Do not add raw provider URLs, query parameters, payloads, user conversion values or AI packet hashes to routine telemetry.

## Performance

Performance work is evidence-driven. Deterministic growth budgets are merge gates; noisy lab timings remain recorded evidence until the CI environment can support a stable threshold.

The 2026-10-02 green production build after the demand-loading and Saved-continuity passes measured:

- core application JavaScript: about 19.50 kB gzip, down from 25.69 kB before demand-loading;
- combined converter + picker enhancement: about 3.10 kB gzip;
- consolidated local saved-state + Saved-page enhancement: about 5.94 kB gzip;
- single rate-chart chunk: about 54.70 kB gzip;
- all JavaScript across core and lazy chunks: about 83.24 kB gzip;
- application stylesheet: about 20.66 kB gzip.

Shared HTMX, typography, CSS and the small race-sensitive AI interaction controller stay in the
core entry. Converter/picker, consolidated local Saved behaviour and rate-chart behaviour are
demand-loaded from DOM contracts and rediscovered after HTMX swaps. The former chart-loader wrapper
and separate Saved-page renderer chunk have been removed so each capability has one lazy request.
Browser QA requires low-interaction shell, Same Amount and City Money Profile surfaces to avoid
route-only dynamic JavaScript, while Current Converter, Explore, Saved and Rate Series load only the
enhancements required by their DOM contracts. Current Converter additionally proves that
result-only chunks arrive after interaction rather than in its initial payload.

Current frontend guardrail budgets intentionally leave generous capacity for continued visual refinement while preserving the demand-loaded architecture:

- core JavaScript: <= 32 KiB gzip;
- all JavaScript: <= 128 KiB gzip;
- CSS: <= 32 KiB gzip;
- chart chunk: <= 80 KiB gzip;
- combined converter enhancement chunk: <= 12 KiB gzip;
- consolidated local saved-state chunk: <= 16 KiB gzip;
- initial browser surface: <= 8 requests;
- initial Chromium layout shift: <= 0.15;
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

Use profiling/measurements before introducing caches or infrastructure. When a budget needs to grow, update the code and this rationale together rather than silently widening the threshold. The October 2026 frontend quality pass deliberately reset the client-side guardrails with wider headroom (32 KiB core JS, 128 KiB total JS, 32 KiB CSS and bounded lazy chunks) so premium UI work is not forced into brittle micro-optimizations. These remain regression alarms rather than targets; accessibility, security, correctness and route-isolation gates are unchanged.

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
