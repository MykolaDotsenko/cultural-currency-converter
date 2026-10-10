#!/usr/bin/env bash
set -euo pipefail

python manage.py migrate --noinput
# Never silently seed an empty database: it could be a lost/ephemeral store.
python manage.py check_reference_catalog

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-10000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
