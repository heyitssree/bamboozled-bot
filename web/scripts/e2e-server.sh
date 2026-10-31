#!/bin/sh
# Starts the REAL Python server (dev auth, loopback only) serving the mock-Discord build of the web app.
set -e
cd "$(dirname "$0")/.."
VITE_MOCK_DISCORD=1 npx vite build --outDir dist-mock >/dev/null && node scripts/inline-css.mjs dist-mock >/dev/null
cd ..
DB="$(mktemp -d)/e2e.db"
exec env BAMBOOZLED_DEV_AUTH=1 BAMBOOZLED_ENV=test BAMBOOZLED_PORT="${PORT:-8481}" BAMBOOZLED_WEB_DIST=web/dist-mock \
  BAMBOOZLED_DB_PATH="$DB" LOG_TO_FILE=0 \
  BAMBOOZLED_SETTINGS_JSON='{"activity.reconnect_grace_seconds": 3, "activity.max_rooms": 200}' \
  "${PYTHON:-.venv/bin/python}" -m bamboozled
