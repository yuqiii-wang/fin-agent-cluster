#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
[[ -z "${DATABASE_URL:-}" ]] && source "$DIR/../.env"
DB_URL_INTERNAL=$(echo "$DATABASE_URL" | sed 's/@[^/]*\//@localhost\//')

docker exec -i "${CONTAINER:-postgres-pg18-trixie}" psql "$DB_URL_INTERNAL" -v ON_ERROR_STOP=1 <<'SQL'
DROP SCHEMA IF EXISTS fin_agents    CASCADE;
DROP SCHEMA IF EXISTS fin_strategies CASCADE;
DROP SCHEMA IF EXISTS fin_markets    CASCADE;
SQL
echo "done."
