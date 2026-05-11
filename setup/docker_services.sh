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
