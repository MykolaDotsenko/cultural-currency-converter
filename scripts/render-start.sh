#!/usr/bin/env bash
set -euo pipefail

python manage.py migrate --noinput
python manage.py seed_reference_data
python manage.py seed_story_data
python manage.py seed_destination_context

exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-10000}" \
  --workers "${WEB_CONCURRENCY:-2}" \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -
