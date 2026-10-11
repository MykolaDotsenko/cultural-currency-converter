#!/usr/bin/env bash
set -euo pipefail

# Bootstrap is an explicit, short-lived operator action for a NEW PostgreSQL
# installation only. An existing user database must never be silently reseeded.
bootstrap="${RENDER_BOOTSTRAP_EMPTY_POSTGRES-false}"
if [[ "$bootstrap" != "false" && "$bootstrap" != "true" ]]; then
  echo "Invalid RENDER_BOOTSTRAP_EMPTY_POSTGRES (expected true or false)." >&2
  exit 64
fi

if [[ "$bootstrap" == "true" ]]; then
  case "${APP_ENV:-}" in
    demo|preview) ;;
    *)
      echo "Initial Render bootstrap is restricted to demo/preview." >&2
      exit 78
      ;;
  esac

  # Tying the opt-in to one reviewed release prevents a stale setting from
  # enabling bootstrap on an unrelated future code revision.
  expected_sha="${RENDER_BOOTSTRAP_APPROVED_SHA:-}"
  actual_sha="${RENDER_GIT_COMMIT:-}"
  if [[ ! "$expected_sha" =~ ^[a-f0-9]{40}$ || "$expected_sha" != "$actual_sha" ]]; then
    echo "Initial Render bootstrap requires the exact approved deploy SHA." >&2
    exit 78
  fi
fi

python manage.py migrate --noinput

if [[ "$bootstrap" == "true" ]]; then
  # No user/reference-table writes until the database is confirmed to be
  # reachable PostgreSQL with all migrations applied.
  python manage.py audit_persistence --require-postgresql >/dev/null

  if python manage.py check_reference_catalog >/dev/null 2>&1; then
    echo "Reference catalog already complete; no bootstrap writes."
  else
    # This checks *all product tables and auth users*, not just the catalog.
    # A partial catalog or any existing account causes a hard failure.
    python manage.py bootstrap_empty_deployment --confirm-empty
  fi
fi

# Never run automatically seeded writes in ordinary deploys or restarts.
python manage.py check_reference_catalog

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-10000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
