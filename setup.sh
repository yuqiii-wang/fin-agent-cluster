#!/usr/bin/env bash
# setup.sh — Entry point for full environment setup.
#
# Sources each setup module from setup/ and runs its function in order.
# All modules are independently executable (bash setup/tls.sh --force) and
# can also be sourced for programmatic use.
#
# Usage: bash setup.sh [OPTIONS]
#
# Options:
#   --keep-volumes       Keep existing postgres volumes (skip stale-version check).
#                        Default: remove any volume whose PG version ≠ 18.
#   --keep-redis         Keep existing Redis volumes (skip flush).
#                        Default: remove redis_0_data and redis_1_data volumes.
#   --force-tls          Regenerate TLS cert even if it already exists.
#   --skip-db-schema     Skip SQL schema setup (useful when DB is already up to date).
#   --skip-ollama        Skip Ollama model creation and warm-up.
#   -h, --help           Print this help message and exit.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

find . \( -type f -name "*.pyc" -o -type d -name __pycache__ \) -exec rm -rf {} + 2>/dev/null || true
rm -rf "$SCRIPT_DIR/logs"
mkdir -p "$SCRIPT_DIR/logs"

# ---------------------------------------------------------------------------
# Source all setup modules
# ---------------------------------------------------------------------------
source "$SCRIPT_DIR/setup/tls.sh"
source "$SCRIPT_DIR/setup/postgres_volumes.sh"
source "$SCRIPT_DIR/setup/docker_services.sh"
source "$SCRIPT_DIR/setup/db_schema.sh"
source "$SCRIPT_DIR/setup/ollama_models.sh"

setup_tls              "$@"
setup_postgres_volumes "$@"
setup_redis_volumes    "$@"
setup_docker_services  "$@"
setup_db_schema        "$@"
setup_ollama_models    "$@"
