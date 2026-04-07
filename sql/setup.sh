#!/usr/bin/env bash
set -euo pipefail
CONTAINER="postgres-pg18-trixie"
DIR="$(cd "$(dirname "$0")" && pwd)"
[[ -z "${DATABASE_URL:-}" ]] && source "$DIR/../.env"
# Inside the container the DB is on localhost:5432; strip the host-mapped port.
DB_URL_INTERNAL=$(echo "$DATABASE_URL" | sed 's/@[^/]*\//@localhost\//')
run() { echo "-> $1"; docker exec -i "$CONTAINER" psql "$DB_URL_INTERNAL" -v ON_ERROR_STOP=1 < "$DIR/$1"; }

run fin_markets_0_consts.sql
run fin_markets_1_basics.sql
run fin_markets_2_ext_min.sql
run fin_markets_3_ext_mappings.sql
run fin_markets_4_ext_all.sql
run fin_strategies_0_const.sql
run fin_strategies_1_nums_to_sentiments.sql
run fin_strategies_3_judgement_history.sql
run fin_strategies_2_dims.sql
run fin_strategies_4_analysis_snapshots.sql
run fin_agents.sql
echo "done."
