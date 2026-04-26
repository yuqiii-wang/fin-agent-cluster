#!/usr/bin/env bash
# setup/docker_services.sh — Bring up all Docker Compose services.
#
# Usage (standalone):  bash setup/docker_services.sh [--foreground]
# Usage (sourced):     source setup/docker_services.sh && setup_docker_services [--foreground]
#
# Flags:
#   --foreground   Run docker compose in the foreground (no -d).
#                  Default: detached mode (-d).

setup_docker_services() {
    local detach=1
    for arg in "$@"; do
        case "$arg" in --foreground) detach=0 ;; esac
    done

    echo "[docker_services] Stopping Kong and removing one-shot containers for a clean re-seed..."
    docker compose stop kong 2>/dev/null || true
    docker compose rm -f kong kong-config-import kong-migrations 2>/dev/null || true

    echo "[docker_services] Dropping and recreating Kong database for a clean slate..."
    docker compose up -d postgres-primary
    # Wait for postgres to be healthy before running psql
    until docker compose exec postgres-primary pg_isready -U "${POSTGRES_USER:-admin}" -q 2>/dev/null; do
        echo "[docker_services] Waiting for postgres-primary to be ready..."
        sleep 2
    done
    docker compose exec postgres-primary psql -U "${POSTGRES_USER:-admin}" -d postgres \
        -c "DROP DATABASE IF EXISTS ${KONG_DB:-kong};"
    docker compose exec postgres-primary psql -U "${POSTGRES_USER:-admin}" -d postgres \
        -c "CREATE DATABASE ${KONG_DB:-kong};"

    echo "[docker_services] Starting Docker Compose services..."
    if [[ $detach -eq 1 ]]; then
        docker compose up -d
    else
        docker compose up
    fi
    echo "[docker_services] Done."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -e
    setup_docker_services "$@"
fi
