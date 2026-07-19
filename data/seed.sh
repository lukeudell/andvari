#!/usr/bin/env bash
# ============================================================
#  file:       data/seed.sh
#  purpose:    one-shot seed: validate environment, generate, load
#  owner:      Luke Udell
#  spdx:       MIT
#  std:        none
#  adr:        none
#  ticket:     none
#  ticket-url: none
#  created:    2026-07-19
# ============================================================
set -euo pipefail

# andvari: generate synthetic data and load it.
# Fails fast on missing configuration rather than loading a half-empty database.

missing=()
for var in PORTFOLIO_DB_HOST PORTFOLIO_DB_PORT PORTFOLIO_DB_USER PORTFOLIO_DB_PASSWORD PORTFOLIO_DB_NAME READER_DB_PASSWORD; do
    if [ -z "${!var:-}" ]; then missing+=("$var"); fi
done
if [ ${#missing[@]} -gt 0 ]; then
    echo "ERROR: missing required environment variables:"
    printf '  - %s\n' "${missing[@]}"
    echo "Check your .env against .env.example"
    exit 1
fi

DB_ARGS="--host $PORTFOLIO_DB_HOST --port $PORTFOLIO_DB_PORT --user $PORTFOLIO_DB_USER --password $PORTFOLIO_DB_PASSWORD --dbname $PORTFOLIO_DB_NAME"

echo ">>> 1/2 generating synthetic data"
python generate_data.py 

echo ">>> 2/2 loading into PostgreSQL"
python load_data.py $DB_ARGS \
    --reader-password "$READER_DB_PASSWORD"

echo ""
echo "=== seeding complete ==="
echo "NOTE: run 'docker compose --profile seed run --rm dbt' next, THEN"
echo "      'python data/grant_reader_access.py' -- grants must follow dbt,"
echo "      or they silently no-op against schemas that do not exist yet."
