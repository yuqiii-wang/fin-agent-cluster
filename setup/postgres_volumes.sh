#!/usr/bin/env bash
# setup/postgres_volumes.sh — Sanity-check and optionally drop stale PG volumes.
#
# Usage (standalone):  bash setup/postgres_volumes.sh [--keep]
# Usage (sourced):     source setup/postgres_volumes.sh && setup_postgres_volumes [--keep]
#
# Flags:
#   --keep-volumes   Skip all volume checks and leave existing volumes untouched.
#                   Default: remove any volume whose PG_VERSION does not match PG 18.
#
# How it works:
#   For each named volume (postgres_primary_data, postgres_replica_data) the
#   function spins up a throwaway container to read PG_VERSION from inside the
#   volume.  If the version is present but not "18" the volume is removed so
#   Docker Compose can re-create it clean on the next `up -d`.  Empty or
#   absent volumes are left alone — they will be initialised by initdb.

_postgres_volumes_pg_major() {
    # Print the PG major version stored in $1 (volume name), or empty string.
    docker run --rm \
        -v "${1}:/pgdata:ro" \
        --entrypoint sh \
        postgres:18.3-trixie \
        -c 'cat /pgdata/18/docker/PG_VERSION 2>/dev/null || true'
}

setup_postgres_volumes() {
    local keep=0
    for arg in "$@"; do
        case "$arg" in --keep-volumes) keep=1 ;; esac
    done

    if [[ $keep -eq 1 ]]; then
        echo "[postgres_volumes] --keep set — skipping volume check"
        return 0
    fi

    local project="${COMPOSE_PROJECT_NAME:-fin-trading-cluster}"
    local pg_major full

    for vol in postgres_primary_data postgres_replica_data; do
        full="${project}_${vol}"
        if docker volume inspect "$full" >/dev/null 2>&1; then
            pg_major=$(_postgres_volumes_pg_major "$full")
            if [[ -n "$pg_major" ]] && [[ "$pg_major" != "18" ]]; then
                echo "[postgres_volumes] Removing incompatible volume $full (PG $pg_major → need PG 18)"
                docker volume rm "$full"
            else
                echo "[postgres_volumes] Volume $full OK (PG ${pg_major:-empty/new})"
            fi
        else
            echo "[postgres_volumes] Volume $full not found — will be created by docker compose"
        fi
    done
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -e
    setup_postgres_volumes "$@"
fi
