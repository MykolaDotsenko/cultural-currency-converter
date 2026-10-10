# Release and Incident Runbook

This runbook is the operational checklist for the current Cultural Currency Converter web product.

It distinguishes **repository evidence** from **deployment evidence**. CI can prove application contracts, clean PostgreSQL restore behaviour and browser quality. It cannot prove a production backup schedule, measured RPO/RTO, object-storage version recovery or a real deployment smoke unless those actions are performed against the target environment.

## Release authority

A release candidate is eligible for deployment only when all applicable gates are green on the exact candidate commit:

- Required merge quality;
- Python 3.13 and Python 3.14;
- PostgreSQL + Redis;
- frontend type/lint/build/performance budgets;
- Chromium full browser quality;
- Firefox and WebKit smoke;
- migration drift and Django deploy checks;
- PostgreSQL backup → clean restore drill;
- accessibility/reflow/keyboard/CSP evidence;
- zero known open P0 and P1 defects at the release cut.

Never reuse green evidence from an older SHA as certification for a newer candidate.

### Enforced repository admission gate

Before approving the release cut, check GitHub's actual effective branch
rules/rulesets for `master`, not merely the existence of CI workflow files:

- branch protection or an equivalent repository ruleset must be **enforced**;
- normal direct pushes, force pushes and branch deletion must be denied;
- failing, missing or stale required checks must block the merge of a PR;
- the required aggregate quality check must correspond to the **exact head SHA**;
- human review and documented audited break-glass authority must match the
  repository's adopted release policy.

A green standalone CI run with `protected=false` is insufficient. See
[#268](https://github.com/MykolaDotsenko/cultural-currency-converter/issues/268)
for the known 2026-10-08 branch-protection gap. Do not mark this gate passed
until the actual GitHub setting and negative enforcement test have been
observed and recorded alongside the pinned release candidate.

## Strict deployed database configuration (PR-02)

The database config now rejects missing `DATABASE_URL` for **every deployed environment** (`demo`, `preview`, `production`). `local` and `test` retain SQLite by default. Existing hosted demo settings may still be using ephemeral SQLite until an approved cutover, so **do not merge/deploy this rule into the active Render service without first validating and provisioning a durable PostgreSQL database and any existing user-data migration/backup requirements**. A startup failure is expected when `APP_ENV=demo` lacks `DATABASE_URL`; this is a safety guard, not evidence of a broken database.

Pass the PR-01 read-only audit after migrations, then verify a disposable owner-scoped scenario survives a controlled restart **and** separate deploy. Preserve current user data, never assume an empty database is safe to replace, and retain the rollback/restore path. PostgreSQL credentials, connection names and hosts must not appear in shared reports.

## Strict production configuration

The hosted portfolio demo is not evidence that strict production infrastructure is configured.

Before a strict production release, verify:

- `APP_ENV=production`;
- a unique production `DJANGO_SECRET_KEY`;
- explicit `DJANGO_ALLOWED_HOSTS`;
- correct HTTPS mode and trusted proxy topology;
- positive HSTS configuration after HTTPS topology is verified;
- explicit CSP mode;
- PostgreSQL `DATABASE_URL`;
- shared Redis `CACHE_URL`;
- optional `API_TRUSTED_PROXY_CIDRS` only after verifying actual proxy CIDRs, right-to-left X-Forwarded-For provenance, and direct-access behavior; without this opt-in quotas use the server peer and shared proxies may aggregate users;
- S3-compatible managed-media storage with bucket, region and public HTTPS origin;
- provider credentials only when the corresponding optional runtime capability is enabled.

Test-only fixtures are never production capabilities. Production configuration must reject:

- `AI_RUNTIME_TEST_FIXTURE_ENABLED=true`;
- `AI_CAMERA_TEST_FIXTURE_ENABLED=true`.

## Read-only Render deployment configuration contract (PR-04)

Before promoting a release, compare the actual Render service's **nonsecret
metadata** with `render.yaml`: service name, branch, build/start commands,
health-check path, auto-deploy mode/trigger. The repository currently expects
`checksPass` and `/health/ready/`; the observed Render service used
`commit` and an empty health-check path on 2026-10-10.

Export only the public/nonsecret service configuration as a local JSON object
(`name`, `branch`, `autoDeploy`, `autoDeployTrigger`,
`serviceDetails.{buildCommand,startCommand,healthCheckPath}`). Do **not**
export tokens, deployment secrets or environment variable values.

```bash
python scripts/check_render_service_contract.py --service-json /secure/operator/render-service.json
```

The checker reads the single web-service scalar fields from `render.yaml`,
compares them with that export, returns exit code 1 on drift/incomplete input,
and prints **field names only**, never observed values. A matching contract
does not prove Render health, data durability or an auto-deploy trigger fired;
use the exact live SHA check and database recovery drill separately.
Resolving actual Render settings is an explicitly reviewed operator action,
not an automatic change made by this diagnostic.

## Deployed revision identity and drift gate

The read-only, DB-free **GET/HEAD** `/health/revision/` endpoint is independent
of liveness/readiness. It returns exactly:

```json
{"status":"known","revision":"<full-40-character-git-sha>"}
```

or `{"status":"unknown","revision":null}` with HTTP 200 when no trustworthy
revision is available. Both responses use `Cache-Control: private, no-store`.
An unknown revision does **not** mean liveness failure; it does mean that a release
**cannot be certified**. Only the public commit SHA is returned—no deployment
credentials, bucket IDs, runtime settings, environment variables or raw errors.

Render supplies `RENDER_GIT_COMMIT` at runtime. For other hosting platforms,
set `APP_RELEASE_SHA` to the **exact deployed** 40-character commit SHA, never a
floating branch name. If both are configured they must match. Absent, malformed,
truncated or conflicting values fail closed to `unknown`.

After the target deploy is reported live, compare the **pinned release SHA**
(the revision actually approved in CI, not an automatically refreshed branch):

```bash
python scripts/check_deployment_revision.py \
  --url https://cultural-currency-converter-mykola.onrender.com/health/revision/ \
  --expected-sha <APPROVED_FULL_RELEASE_SHA>
```

The verifier exits **0** only for a complete exact match; it exits **1** for
unknown, mismatch, invalid payload, redirect, transport failure or invalid input.
It rejects non-HTTPS remote URLs and never follows redirects. Local test servers
on `localhost`, `127.0.0.1` or `::1` may use HTTP. No external provider,
Render API key or database permission is required.

Keep the raw output and timestamp with the Render deploy ID, exact approved Git
SHA and CI run IDs in **external immutable release evidence**. Compare that ID
against the actual live deployment in the hosting dashboard. A matching endpoint
SHA alone does **not** prove database recovery, media readiness, infrastructure
correctness or full production certification; those have separate gates below.

## Scheduled detection of deployment drift

The repository's `.github/workflows/production-deployment-drift.yml` is
configured for twice-daily checks (08:17 and 20:17 UTC) and explicit manual
dispatch. Confirm a real completed run and its exact observed SHA; the presence
of the YAML/schedule alone is not execution evidence.
It checks out the latest `master` and runs the same standalone fail-closed
revision verifier against the public Render service. A bounded six-attempt
retry window allows the free instance to wake up without requiring Render
API credentials, production database access, user data or any write
permission. Every attempt must match the **full 40-character commit SHA**.
Unknown revisions, 404s, redirects, persistent timeouts and mismatches keep
the workflow red; no passing result is inferred from an HTTP 200 alone.

**Important scope:** this monitoring policy expects the configured
auto-deploying `master` demo to run the latest reviewed commit. It detects
drift at scheduled observation times, not continuously, and a failed monitor
does **not** prove which GitHub/Render integration component is responsible.
If the production release policy later intentionally pins an older
independently approved candidate, update the monitor's expected-revision
policy in a reviewed PR rather than weakening the verifier or accepting
permanent false alarms.

On failure, compare the workflow's expected SHA, the exact Render live
deploy commit and the deployment event history. Review the GitHub integration,
configured branch, actual auto-deploy trigger and readiness health path
against `render.yaml`. Track findings in the deployment incident
([#266](https://github.com/MykolaDotsenko/cultural-currency-converter/issues/266))
and keep any repair/deploy separate from this read-only monitor. Once a
new deploy is live, independently perform the pinned release-SHA check above
and the full smoke/recovery certification gates below; a scheduled green
check does **not** grant 100/100 release certification.

### Read-only database persistence preflight (PR-01)

Before changing any database, schema or Render environment variable, run the
operator-only diagnostic inside the application runtime:

```bash
python manage.py audit_persistence
# Gate for a deployment intended to use durable PostgreSQL:
python manage.py audit_persistence --require-postgresql
```

The command performs one read-only `SELECT 1` and Django migration-plan
inspection. It emits **only** the allow-listed environment/engine family,
connection state, migration state, a deployed-SQLite risk flag and
`"durability": "unverified"`. It does not print connection URLs, hosts, paths,
user data or exception details; it has no HTTP endpoint and never writes a probe
record. The optional flag exits nonzero if PostgreSQL is not reachable or
migrations are not current.

**Important:** PostgreSQL preflight success is *not* proof of persistence,
backups, retained media, data ownership, or actual recovery. A deployed SQLite
risk indicates a potentially ephemeral runtime, **not** proven data loss.
Record only the sanitized output and release SHA. For issue #302, an explicitly
approved, disposable test-user/test-scenario drill must still demonstrate
survival of **restart and a separate deploy**, without touching real users'
records. If the storage is ephemeral, pause user-data writes or restrict the
demo while planning a reviewed backup, migration, rollback and data-preservation
procedure. Never infer a safe cutover from the diagnostic alone.

## Reference data initial bootstrap and startup gate (PR-03)

The Render web start command runs migrations and a **read-only reference-catalog
check**; it no longer seeds the database on every restart. A new empty database
therefore **fails closed** after schema creation instead of being silently
populated and hiding data-loss incidents. Lack of reference data is not proof
of data loss, but must be investigated before activating account writes.

Only after an operator verifies a **new isolated database with no existing
user or application records**, and has documented a backup/recovery and cutover
plan, run the following once with web traffic stopped:

```bash
bash scripts/render-initial-bootstrap.sh
```

The script migrates, verifies that there are **no existing auth users** and that
*all managed product-owned model tables* are empty (without misclassifying built-in
Django permissions as user data), runs the explicit seed commands and verifies baseline
country/currency relationships. It refuses initial seeding when any app record
already exists; it neither deletes records nor bypasses an incomplete catalog.
A partially populated target must be reviewed or restored, never automatically
reseeded. Run ingestion/update commands on their own reviewed schedule later;
they are not an application process startup concern.

The ordinary deployed startup still applies schema migrations because the
current Render free service does not use a separately verified release-phase
migration job. Move migrations to an approved single-writer release step when
the hosting setup supports it; do not confuse the absence of repeated seeds
with a proof of data durability.

## Opt-in scheduled scenario notification delivery (PR-06)

The generation service and management command already deduplicate owner-scoped
in-app messages. The reviewed scheduler entrypoint is deliberately **not**
activated by this PR; it must not run against the existing ephemeral demo.

Once a durable PostgreSQL deployment, recoverability, seed readiness and
notification preference ownership are verified, the operator may configure a
separate scheduler job using the same reviewed code SHA and environment,
with this command:

```bash
SCENARIO_NOTIFICATIONS_SCHEDULER_APPROVED=true \
  bash scripts/render-notification-job.sh
```

The script requires the exact approval string `true`, then runs the
credential-free PostgreSQL/migration audit and read-only reference catalog
check **before** `deliver_scenario_notifications`. Missing approval,
SQLite, unavailable PostgreSQL, pending migrations or missing baseline
reference pairs aborts without generating notifications. Approval is an
operational decision documented separately; it is **not** automatically
granted by CI and must not be inferred merely from a configured DATABASE_URL.

Deploying a Render Cron Job creates a separate billed infrastructure
resource and requires shared, approved environment configuration. **No cron
service, schedule, credentials or billing changes are created by this PR.**
Once separately authorized, verify exact deployed SHA, scheduled execution,
one enabled disposable pre-trip message, retry deduplication, failure
visibility and timezone cadence. Do not claim "automated delivery" until
a real scheduled run has completed successfully.

## Guarded economic-context scheduled ingestion (PR-07)

The existing World Bank, Eurostat and OECD ingestion command already validates
all external responses **before** its database transaction. For scheduled
runs only, use the new `--require-observations` flag so a successful-but-empty
provider result does not silently count as a completed refresh. This flag
raises a nonzero error before any writes if zero normalized observations are
returned; manual exploratory `--dry-run` still permits empty coverage.

After explicit operator approval of provider licensing, request volume,
freshness expectations and verified PostgreSQL durability, a scheduler may
invoke (example for World Bank, **not activated by this PR**):

```bash
ECONOMIC_CONTEXT_SCHEDULER_APPROVED=true ECONOMIC_SYNC_SOURCE=world_bank \
  bash scripts/render-economic-sync-job.sh
```

The script refuses an absent approval, requires explicit allow-listed provider
selection, verifies PostgreSQL and the reference catalog, then runs the
existing ingestion through the strict nonempty gate. The supported provider
choices are `world_bank`, `eurostat`, `oecd`, `all`; broad `all` sweeps
require separate operational review because of source coverage/volume. It
creates **no Render Cron Job**, subscription, credentials or billing changes.
Actual automated freshness is unverified until a real scheduled execution
and audit trail exist.

## Guarded public-holiday scheduled ingestion (PR-08)

`sync_public_holidays` deliberately reconciles a country/year scope and
can unpublish previously observed holidays that disappeared from a later
provider response. A transient **empty** provider result must not silently
retire the full holiday set during unattended operation.

The opt-in `--require-nonempty-scopes` switch raises an error **before the
transaction** when any requested country/year has zero observations.
Unattended jobs must use this strict mode. Manual synchronization retains
the existing explicit reconciliation behaviour for carefully reviewed cases,
including legitimately empty scopes.

The unactivated guarded entrypoint requires explicit approval, a specified
country and a bounded horizon:

```bash
HOLIDAY_SYNC_SCHEDULER_APPROVED=true HOLIDAY_SYNC_COUNTRY=FI \
  HOLIDAY_SYNC_YEARS_AHEAD=1 bash scripts/render-holiday-sync-job.sh
```

PostgreSQL and baseline reference data checks run before any provider call.
No cron service, extra billing or Render environment was created/changed in
this PR. After durable storage and operator approval, schedule a bounded set
of supported country/year scopes and test retries, no-data failures,
freshness, national-only presentation and actual scheduler execution.
A strict rejection should be reviewed, not bypassed automatically.

## Background job completion telemetry (PR-09)

The three approved *Django management commands* now produce a single structured
`background_job_result` event per completed execution under the
`cultural_currency.jobs` logger. The payload is intentionally limited to:
`job` (`scenario_notifications`, `economic_context`, or `public_holidays`),
`outcome`, `duration_ms`, `dry_run`, optional aggregate
`records_processed/created/updated/retired`, and fixed `error_code=job_failed`
on failure. No owner IDs, scenario details, input amounts, URL/credentials,
provider error text, raw observations or exception tracebacks are included.

For ingestion, `dry_run=true` indicates **rolled-back would-be write counts**,
not persisted changes. Notification `records_processed` counts **newly created
in-app deliveries**, not evaluated preferences. Holiday
`records_processed` counts fetched country/year scopes.

Command outputs and return codes remain unchanged, and exceptions still
propagate to the scheduler. These events can be used by an operator to
monitor jobs **after real jobs are activated**. They do not prove cadence,
last-success freshness across missed invocations or alerts; those require
an external scheduled-run history/monitor. The guarded shell entrypoints
may refuse a job *before the Django process runs*, in which case these
application lifecycle events are correctly absent; inspect scheduler
exit status and job logs as well.

## Database backup and restore

Before a risky deployment or schema/data migration, produce a PostgreSQL custom-format backup with:

```bash
DATABASE_URL="..." BACKUP_PATH="/secure/path/pre-release.dump" \
  sh scripts/postgres_backup.sh
```

The backup command:

- refuses accidental overwrite unless explicitly authorized;
- validates that `pg_restore` can read the archive;
- writes a SHA-256 sidecar.

Restore only into a **fresh/empty** target database:

```bash
RESTORE_DATABASE_URL="..." \
BACKUP_PATH="/secure/path/pre-release.dump" \
RESTORE_CONFIRM=restore-empty-database \
  sh scripts/postgres_restore.sh
```

Then verify:

```bash
DATABASE_URL="..." python manage.py check --database default
DATABASE_URL="..." python manage.py migrate --check
```

Run application smoke checks before cutover. Keep the old database available until recovery confidence is established.

Do not blindly roll database schema backward after production traffic has used a migration. Prefer roll-forward when safe.

### Disposable relational recovery probe (PR-10)

The PostgreSQL 18.6 integration workflow now creates a **synthetic test-only**
owner with an unusable password, a saved budget, its immutable initial
FX observation and confirmed spending before the custom-format backup.
After restoring into a separate empty target database, it re-runs a
read-only integrity check of ownership, currencies, amounts and relations.

`verify_recovery_fixture` requires `APP_ENV=test` and the explicit
`--confirm-ci-only` flag; an existing fixture is never overwritten.
The synthetic observation represents no real FX provider or customer.
This exercise **does not certify production** storage retention, backup
recency, object recovery, RPO/RTO or actual Render restart/redeploy. Record
those in a separate operator-approved real-environment drill.

## Managed-media recovery

PostgreSQL recovery restores media metadata, not object bytes.

Before claiming operations/recovery certification for a deployment:

1. confirm the production bucket has the intended versioning/retention policy;
2. record the policy/evidence outside application secrets;
3. restore a known managed-media object/version into a safe recovery location;
4. verify its checksum/content and application-facing object name;
   For a specifically restored, published MediaAsset with a recorded
   SHA-256 checksum, run the **read-only byte-level** verification:
   ```bash
   python manage.py verify_media_recovery --asset-id <APPROVED_PUBLISHED_ASSET_ID>
   ```
   This opens the configured Django storage backend, streams up to 64 MiB,
   compares the bytes to the recorded checksum and fails without writing
   anything. The tool prints neither object keys nor storage exceptions.
   A passing test does **not** prove S3 bucket versioning, prior-version
   retention, a successful real restore or unrelated media assets.
5. run:
   ```bash
   python manage.py report_curated_media_coverage --strict
   ```
   against the deployment data where applicable.

A missing optional image must degrade to the intentional no-image state; it must not invalidate conversion truth.

## Exact live revision + health preflight (PR-05)

In addition to the revision-only check, the operator can run a **read-only**
three-endpoint preflight against the exact pinned release SHA:

```bash
python scripts/check_release_smoke.py \
  --url https://cultural-currency-converter-mykola.onrender.com/health/revision/ \
  --expected-sha <APPROVED_FULL_RELEASE_SHA>
```

For a strict production environment expected to provide shared Redis, append
`--require-shared-cache`. The preflight checks full revision equality, process
liveness and DB readiness in order. A degraded or unavailable readiness cannot
be misreported as success. The tool rejects remote non-HTTPS endpoints,
redirects, oversized/non-JSON responses and missing status fields; failure
messages use fixed codes, not provider exception details.

**Scope boundary:** green means revision/HTTP/DB-readiness only. It does not
demonstrate persistent storage, backups, media recovery, real provider
integrations, release governance or successful user journeys. Keep the
disposable-record restart/deploy drill and independent RC smoke below.
Do not automatically deploy, mutate a database or change Render settings
from this preflight.

## RC deployment smoke

After deploying an RC, record the deployment identifier and exact Git SHA, then verify:

1. `/health/live/` returns process liveness;
2. `/health/ready/` confirms the durable database and reports cache state according to its contract;
3. public HTTPS redirect/HSTS/CSP behaviour matches the deployment topology;
4. static assets load from the expected build;
5. the complete user loop succeeds:

```text
Convert
→ Context
→ Budget
→ Save
→ Reopen
→ Re-check
→ Camera
→ Confirm
→ Spend
→ Offline Pack
→ Explore
→ Compare
```

For Camera, verify the upload is explicitly initiated, the extracted amount must be confirmed, and spend requires a separate explicit action.

For Offline Pack, verify the downloaded HTML states that offline data is stored rather than live and opens without network dependencies. For the installed PWA, verify ordinary navigation HTML is absent from Cache Storage before opt-in; explicitly save one trip, open its read-only snapshot offline, change saved scenario state, confirm the copy becomes out of date, refresh it explicitly, and verify removal clears the private cache entry.

For the PWA shell, verify the manifest is installable, the root-scoped service worker precaches only the generic offline shell/public static assets, and an offline navigation to a private Saved/account path resolves to the generic shell rather than a cached private page. Inspect Cache Storage and confirm there is no account/scenario/notification/admin HTML.

For saved scenarios/comparisons, verify reopening never silently refreshes financial values; re-check is a distinct explicit action.

## Optional-capability degradation drill

A release candidate must remain useful when optional systems are disabled or unavailable.

### Runtime text AI

Action:

- disable `AI_RUNTIME_EXPLANATION_ENABLED` or remove the optional provider capability according to deployment config.

Expected:

- conversion, context, budget, Explore and comparison remain deterministic;
- no AI output becomes financial truth;
- supported fallback/error states remain usable.

### Camera

Action:

- disable `AI_CAMERA_EXTRACTION_ENABLED`.

Expected:

- saved budget scenarios remain usable;
- manual confirmed-spend entry remains available;
- no stored scenario state is lost.

### Redis/shared cache

Expected:

- readiness may report degraded cache state according to the documented contract;
- cache-dependent coordination fails open where designed;
- PostgreSQL-backed durable state remains authoritative.

### FX provider

Expected:

- provider errors never fabricate a fresh rate;
- stale fallback is labelled as stale only when the canonical policy permits it;
- provider failure cannot mutate saved immutable observations.

### Destination context/media

Expected:

- optional enrichment/media failure degrades locally;
- the conversion remains intact;
- no city/national fallback becomes silent.

## Incident response

### Database unavailable

1. Treat failed database readiness as a service-impacting incident.
2. Stop unsafe writes/cut traffic according to deployment controls.
3. Establish whether the primary database can be recovered safely.
4. If restore is required, restore into a fresh database using the verified backup path above.
5. Run checks/migration verification and smoke tests.
6. Cut over only after the recovered database is verified.

### AI/provider incident

1. Prefer disabling the optional capability over risking untrusted output.
2. Preserve deterministic application results.
3. Inspect structured provider/error telemetry; do not add raw user financial payloads to logs.
4. Re-enable only after provider behaviour and application validation are verified.

### Managed-media incident

1. Keep application financial surfaces serving without media.
2. Verify object-store version/retention state.
3. Restore known objects independently of PostgreSQL metadata.
4. Run strict media coverage/readiness reporting before declaring recovery complete.

### Bad application release

1. Determine whether the release contains schema/data changes.
2. Prefer a forward fix when production data has already crossed a migration boundary.
3. If application rollback is safe and schema-compatible, redeploy the previous known-good application commit.
4. If database recovery is required, use the fresh-database restore procedure rather than destructive in-place cleanup.

## RPO/RTO evidence

Do not publish aspirational RPO/RTO numbers.

For the actual production deployment, record:

- timestamp of the newest recoverable backup at drill start;
- backup age;
- restore start/end timestamps;
- database verification completion time;
- object-storage restore time where relevant;
- full application-ready time after cutover/smoke.

Only measured values from the real deployment can support an RPO/RTO claim.

## Release evidence record

For every certified release, retain at minimum:

- exact Git SHA;
- PR/release identifier;
- CI run identifiers for Python/PostgreSQL/frontend/browser gates;
- P0/P1 issue query snapshot;
- deployment identifier;
- backup identifier/checksum and creation time;
- clean-restore result;
- object-storage version/restore evidence;
- RC smoke result;
- measured RPO/RTO drill values when claimed;
- any accepted exceptions with owner and follow-up.

If a required item is unavailable, mark certification **pending** rather than inferring success.
