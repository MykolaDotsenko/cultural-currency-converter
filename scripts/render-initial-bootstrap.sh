#!/usr/bin/env bash
set -euo pipefail

# Invoke only on a verified new, isolated database with traffic stopped.
# A strict read-only preflight prevents accidental reseeding of existing data.
python manage.py migrate --noinput
python manage.py check_reference_catalog --require-empty
python manage.py seed_reference_data
python manage.py seed_story_data
python manage.py seed_destination_context
python manage.py check_reference_catalog
