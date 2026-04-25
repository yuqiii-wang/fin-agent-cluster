#!/usr/bin/env bash
# setup/frontend_env.sh — Write frontend/.env.local for Kong HTTPS+HTTP/2 SSE port.
#
# Usage (standalone):  bash setup/frontend_env.sh [--force]
# Usage (sourced):     source setup/frontend_env.sh && setup_frontend_env [--force]
#
# Flags:
#   --force-frontend   Overwrite an existing frontend/.env.local.
#                     Default: skip if the file already exists.

setup_frontend_env() {
    local force=0
    for arg in "$@"; do
        case "$arg" in --force-frontend) force=1 ;; esac
    done

    if [[ $force -eq 0 ]] && [[ -f frontend/.env.local ]]; then
        echo "[frontend_env] frontend/.env.local already exists — skipping (--force to overwrite)"
        return 0
    fi

    echo "[frontend_env] Writing frontend/.env.local (VITE_SSE_URL=https://localhost:8889)"
    printf 'VITE_SSE_URL=https://localhost:8889\n' > frontend/.env.local
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -e
    setup_frontend_env "$@"
fi
