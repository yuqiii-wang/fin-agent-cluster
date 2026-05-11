#!/bin/bash
# Run all SQL schema files against the primary PostgreSQL instance.
# On --drop, also verifies all schemas/tables/types are gone, then resyncs
# the replica via pg_basebackup.
# Usage: bash sql/setup_db_schema.sh [--drop] [--yes|-y]
set -e

DROP_FIRST=true
CONFIRM=true

for arg in "$@"; do
    case "$arg" in
        --drop)  DROP_FIRST=true ;;
        --yes|-y) CONFIRM=true ;;
    esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/../docker-compose.yml"
ENV_FILE="$SCRIPT_DIR/../.env"

[ ! -f "$ENV_FILE" ] && echo "Error: .env not found at $ENV_FILE" >&2 && exit 1

DATABASE_PG_URL=$(grep -E '^(export )?DATABASE_PG_URL=' "$ENV_FILE" \
    | head -1 \
    | sed -E 's/^(export )?DATABASE_PG_URL=//' \
    | tr -d '"'"'" \
    | tr -d '\r')

[ -z "$DATABASE_PG_URL" ] && echo "Error: DATABASE_PG_URL not set in .env" >&2 && exit 1

_psql() {
    MSYS_NO_PATHCONV=1 docker run --rm --network host \
        -e PGOPTIONS='-c client_min_messages=warning' \
        postgres:18.3-trixie \
        psql "$DATABASE_PG_URL" -v ON_ERROR_STOP=1 -q "$@"
}

if $DROP_FIRST; then
    if ! $CONFIRM; then
        read -r -p "DROP fin_agents, fin_markets, fin_strategies, fin_users CASCADE? Type 'yes': " answer
        [ "$answer" != "yes" ] && echo "Aborted." >&2 && exit 1
    fi

    _psql -c "
        SET client_min_messages = WARNING;
        DROP SCHEMA IF EXISTS fin_agents     CASCADE;
        DROP SCHEMA IF EXISTS fin_markets    CASCADE;
        DROP SCHEMA IF EXISTS fin_strategies CASCADE;
        DROP SCHEMA IF EXISTS fin_users      CASCADE;
    " >/dev/null

    # Verify no schema, table, or type from the app namespaces remains.
    REMAINING=$(_psql -tAq -c "
        SELECT 'schema:' || nspname
        FROM pg_catalog.pg_namespace
        WHERE nspname IN ('fin_agents','fin_markets','fin_strategies','fin_users')
        UNION ALL
        SELECT 'table:' || schemaname || '.' || tablename
        FROM pg_catalog.pg_tables
        WHERE schemaname IN ('fin_agents','fin_markets','fin_strategies','fin_users')
        UNION ALL
        SELECT 'type:' || n.nspname || '.' || t.typname
        FROM pg_catalog.pg_type t
        JOIN pg_catalog.pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname IN ('fin_agents','fin_markets','fin_strategies','fin_users')
          AND t.typtype != 'b';
    ")
    [ -n "$REMAINING" ] && echo "Error: objects still present after DROP:" >&2 \
        && echo "$REMAINING" >&2 && exit 1
fi

# Run SQL files in dependency order.
SQL_FILES=(
    "fin_users.sql"
    "fin_agents.sql"
    "fin_markets_consts.sql"
    "fin_markets.sql"
    "fin_strategies.sql"
)

for sql_file in "${SQL_FILES[@]}"; do
    filepath="$SCRIPT_DIR/$sql_file"
    [ ! -f "$filepath" ] && echo "Error: $sql_file not found" >&2 && exit 1
    MSYS_NO_PATHCONV=1 docker run --rm \
        -e PGOPTIONS='-c client_min_messages=warning' \
        -v "$SCRIPT_DIR:/sql:ro" \
        --network host \
        postgres:18.3-trixie \
        psql "$DATABASE_PG_URL" -v ON_ERROR_STOP=1 -q -f "/sql/$sql_file" >/dev/null
done

# On drop+rebuild, wipe and restart the replica so replica/setup.sh triggers
# a fresh pg_basebackup from the now-updated primary.
if $DROP_FIRST; then
    docker compose -f "$COMPOSE_FILE" stop postgres-replica >/dev/null
    docker compose -f "$COMPOSE_FILE" run --rm --entrypoint bash \
        postgres-replica -c "rm -rf /var/lib/postgresql/18/docker/* /var/lib/postgresql/18/docker/.[!.]*" \
        >/dev/null 2>&1 || true
    docker compose -f "$COMPOSE_FILE" start postgres-replica >/dev/null
fi
