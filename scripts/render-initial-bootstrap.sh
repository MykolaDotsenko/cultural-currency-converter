#!/usr/bin/env bash
set -euo pipefail

# Invoke only on a verified new, isolated database with traffic stopped.
# A strict read-only preflight prevents accidental reseeding of existing data.
python manage.py migrate --noinput
python manage.py bootstrap_empty_deployment --confirm-empty
python manage.py check_reference_catalog
