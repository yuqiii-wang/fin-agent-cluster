#!/usr/bin/env bash
# setup/db_schema.sh — Run all SQL schema files against the configured PostgreSQL database.
#
# Usage (standalone):  bash setup/db_schema.sh
# Usage (sourced):     source setup/db_schema.sh && setup_db_schema
#
# Delegates to sql/setup_db_schema.sh which reads DATABASE_PG_URL from .env.

setup_db_schema() {
    echo "[db_schema] Running database schema setup..."
    ./sql/setup_db_schema.sh
    echo "[db_schema] Done."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -e
    setup_db_schema "$@"
fi
