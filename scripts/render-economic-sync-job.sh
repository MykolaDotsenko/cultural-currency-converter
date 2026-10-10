#!/usr/bin/env bash
set -euo pipefail

if [[ "${ECONOMIC_CONTEXT_SCHEDULER_APPROVED:-}" != "true" ]]; then
  echo "Economic sync scheduler not approved." >&2
  exit 78
fi

# Require explicit provider selection to avoid accidental all-provider sweeps.
case "${ECONOMIC_SYNC_SOURCE:-}" in
  world_bank|eurostat|oecd|all) ;;
  *)
    echo "An explicit approved ECONOMIC_SYNC_SOURCE is required." >&2
    exit 64
    ;;
esac

python manage.py audit_persistence --require-postgresql >/dev/null
python manage.py check_reference_catalog >/dev/null
exec python manage.py sync_economic_context \
  --source "$ECONOMIC_SYNC_SOURCE" --require-observations
