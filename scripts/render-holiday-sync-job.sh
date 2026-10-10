#!/usr/bin/env bash
set -euo pipefail

if [[ "${HOLIDAY_SYNC_SCHEDULER_APPROVED:-}" != "true" ]]; then
  echo "Holiday sync scheduler not approved." >&2
  exit 78
fi

# Require a reviewed scope; never silently sweep every catalog country.
country="${HOLIDAY_SYNC_COUNTRY:-}"
years="${HOLIDAY_SYNC_YEARS_AHEAD:-1}"
if [[ ! "$country" =~ ^[A-Z]{2,3}$ ]] || [[ ! "$years" =~ ^[0-5]$ ]]; then
  echo "A valid country code and years-ahead (0-5) are required." >&2
  exit 64
fi

python manage.py audit_persistence --require-postgresql >/dev/null
python manage.py check_reference_catalog >/dev/null
exec python manage.py sync_public_holidays \
  --country "$country" --years-ahead "$years" --require-nonempty-scopes
