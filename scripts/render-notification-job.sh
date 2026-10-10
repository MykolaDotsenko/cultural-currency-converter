#!/usr/bin/env bash
set -euo pipefail

# Invoked ONLY by an operator-approved scheduler after database persistence,
# restore and release smoke have been verified independently.
if [[ "${SCENARIO_NOTIFICATIONS_SCHEDULER_APPROVED:-}" != "true" ]]; then
  echo "Scheduler not approved: refusing notification writes." >&2
  exit 78
fi

# Fail closed before any notification generation or FX rate probing.
python manage.py audit_persistence --require-postgresql >/dev/null
python manage.py check_reference_catalog >/dev/null

# DB uniqueness, explicit opt-in and cadence guards live in the Django service.
exec python manage.py deliver_scenario_notifications
