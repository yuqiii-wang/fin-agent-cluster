#!/usr/bin/env bash
# setup/db_schema.sh — Run all SQL schema files against the configured PostgreSQL database.
#
# Usage (standalone):  bash setup/db_schema.sh
# Usage (sourced):     source setup/db_schema.sh && setup_db_schema
#
# Delegates to sql/setup_db_schema.sh which reads DATABASE_PG_URL from .env.

# Options for sql/setup_db_schema.sh:
#   --drop              Drop all application schemas (fin_agents, fin_markets, fin_strategies, fin_users) with CASCADE before re-creating them.
#                       Also forces a full pg_basebackup resync of the postgres-replica container.
#   --yes, -y         Skip confirmation prompt when using --drop.
#  bash setup/db_schema.sh --drop --yes


setup_db_schema() {
    echo "[db_schema] Running database schema setup..."
    ./sql/setup_db_schema.sh "$@"
    echo "[db_schema] Done."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -e
    setup_db_schema --drop --yes "$@"
fi
