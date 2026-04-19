#!/bin/bash
# Run all SQL setup files against the configured PostgreSQL database.
# Reads DATABASE_PG_URL from the root .env file.
# Usage: bash sql/setup.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/../.env"

[ ! -f "$ENV_FILE" ] && echo "Error: .env file not found at $ENV_FILE" && exit 1

# Extract DATABASE_PG_URL from .env (handles both export and bare assignments)
DATABASE_PG_URL=$(grep -E '^(export )?DATABASE_PG_URL=' "$ENV_FILE" \
    | head -1 \
    | sed -E 's/^(export )?DATABASE_PG_URL=//' \
    | tr -d '"'"'" \
    | tr -d '\r')

[ -z "$DATABASE_PG_URL" ] && echo "Error: DATABASE_PG_URL not set in .env" && exit 1

echo "Using database: $DATABASE_PG_URL"

# Run SQL files in dependency order:
#   kong       (no deps)
#   fin_users  (no deps)
#   fin_agents (no deps)
#   fin_markets       (refs fin_agents)
#   fin_markets_consts (refs fin_markets)
#   fin_strategies    (refs fin_agents)
SQL_FILES=(
    "kong.sql"
    "fin_users.sql"
    "fin_agents.sql"
    "fin_markets.sql"
    "fin_markets_consts.sql"
    "fin_strategies.sql"
)

for sql_file in "${SQL_FILES[@]}"; do
    filepath="$SCRIPT_DIR/$sql_file"
    if [ ! -f "$filepath" ]; then
        echo "Warning: $sql_file not found, skipping."
        continue
    fi
    echo "Running $sql_file ..."
    MSYS_NO_PATHCONV=1 docker run --rm \
        -v "$SCRIPT_DIR:/sql:ro" \
        --network host \
        postgres:18.3-trixie \
        psql "$DATABASE_PG_URL" -f "/sql/$sql_file"
    echo "  Done: $sql_file"
done

echo "All SQL files executed successfully."
