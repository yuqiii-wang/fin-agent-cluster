#!/usr/bin/env bash
# setup/kong_config.sh — Build Kong declarative config via build.py.
#
# Usage (standalone):  bash setup/kong_config.sh
# Usage (sourced):     source setup/kong_config.sh && setup_kong_config

setup_kong_config() {
    echo "[kong_config] Building Kong declarative config..."
    python kong-api-gateway/build.py
    echo "[kong_config] Done."
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    set -e
    setup_kong_config "$@"
fi
