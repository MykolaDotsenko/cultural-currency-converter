#!/usr/bin/env bash
set -euo pipefail

python -m pip install --upgrade pip
python -m pip install .

if ! command -v npm >/dev/null 2>&1; then
  echo "npm is required to build the Vite frontend." >&2
  exit 1
fi

npm --prefix frontend ci
npm --prefix frontend run build
python manage.py collectstatic --noinput
