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
- S3-compatible managed-media storage with bucket, region and public HTTPS origin;
- provider credentials only when the corresponding optional runtime capability is enabled.

Test-only fixtures are never production capabilities. Production configuration must reject:

- `AI_RUNTIME_TEST_FIXTURE_ENABLED=true`;
- `AI_CAMERA_TEST_FIXTURE_ENABLED=true`.

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

## Managed-media recovery

PostgreSQL recovery restores media metadata, not object bytes.

Before claiming operations/recovery certification for a deployment:

1. confirm the production bucket has the intended versioning/retention policy;
2. record the policy/evidence outside application secrets;
3. restore a known managed-media object/version into a safe recovery location;
4. verify its checksum/content and application-facing object name;
5. run:
   ```bash
   python manage.py report_curated_media_coverage --strict
   ```
   against the deployment data where applicable.

A missing optional image must degrade to the intentional no-image state; it must not invalidate conversion truth.

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

For Offline Pack, verify the downloaded HTML states that offline data is stored rather than live and opens without network dependencies.

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
