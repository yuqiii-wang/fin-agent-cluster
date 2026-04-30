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
#   --force-tls          Regenerate TLS cert even if it already exists.
#   --skip-db-schema     Skip SQL schema setup (useful when DB is already up to date).
#   --skip-ollama        Skip Ollama model creation and warm-up.
#   -h, --help           Print this help message and exit.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Source all setup modules
# ---------------------------------------------------------------------------
source "$SCRIPT_DIR/setup/tls.sh"
source "$SCRIPT_DIR/setup/kong_config.sh"
source "$SCRIPT_DIR/setup/postgres_volumes.sh"
source "$SCRIPT_DIR/setup/docker_services.sh"
source "$SCRIPT_DIR/setup/db_schema.sh"
source "$SCRIPT_DIR/setup/ollama_models.sh"

setup_tls              "$@"
setup_kong_config      "$@"
setup_postgres_volumes "$@"
setup_docker_services  "$@"
setup_db_schema        "$@"
setup_ollama_models    "$@"
