#!/bin/bash
# restore.sh — Restore postgres Docker volume data from a pg-backup snapshot.
#
# Usage: ./restore.sh <backup-timestamp-dir>
#   <backup-timestamp-dir>  Path to a specific backup, e.g. pg-backup/20260425_143000
#                           If omitted, lists available backups and exits.
#
# WARNING: postgres-primary and postgres-replica containers must be stopped
# before running this script. The script will abort if they are running.

set -euo pipefail

DOCKER_VOLUMES_ROOT="/var/lib/docker/volumes"

# ── Resolve project root (three levels up: replica → postgres → sql → root) ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

DEST="${PROJECT_ROOT}/pg-backup"
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "${PROJECT_ROOT}" | tr '[:upper:]' '[:lower:]')}"

PRIMARY_VOLUME="${COMPOSE_PROJECT}_postgres_primary_data"
REPLICA_VOLUME="${COMPOSE_PROJECT}_postgres_replica_data"

# ── No argument: list available backups ──────────────────────────────────────
if [[ $# -eq 0 ]]; then
    echo "Available backups in ${DEST}:"
    if [[ -d "${DEST}" ]]; then
        ls -1t "${DEST}"
    else
        echo "  (none)"
    fi
    echo ""
    echo "Usage: $0 <backup-timestamp-dir>"
    exit 0
fi

BACKUP_DIR="$1"
# Allow bare timestamp (e.g. 20260425_143000) as well as full path
if [[ ! -d "${BACKUP_DIR}" ]]; then
    BACKUP_DIR="${DEST}/$1"
fi

if [[ ! -d "${BACKUP_DIR}" ]]; then
    echo "ERROR: backup directory not found: ${BACKUP_DIR}" >&2
    exit 1
fi

# ── Ensure postgres containers are stopped ────────────────────────────────────
for container in postgres-primary postgres-replica; do
    if docker ps --format '{{.Names}}' | grep -q "^${container}$"; then
        echo "ERROR: container '${container}' is still running." >&2
        echo "       Stop it first: docker compose stop postgres-primary postgres-replica" >&2
        exit 1
    fi
done

# ── Helper: restore one volume ────────────────────────────────────────────────
restore_volume() {
    local volume_name="$1"
    local src="${BACKUP_DIR}/${volume_name}"
    local dst="${DOCKER_VOLUMES_ROOT}/${volume_name}/_data"

    if [[ ! -d "${src}" ]]; then
        echo "[restore] WARNING: '${src}' not found in backup — skipping." >&2
        return 0
    fi

    if [[ ! -d "${dst}" ]]; then
        echo "[restore] WARNING: volume path '${dst}' does not exist — skipping." >&2
        return 0
    fi

    echo "[restore] Clearing ${dst}"
    rm -rf "${dst:?}/"*

    echo "[restore] Copying ${src} → ${dst}"
    cp -a "${src}/." "${dst}/"

    local size
    size="$(du -sh "${dst}" | cut -f1)"
    echo "[restore] Done: ${dst} (${size})"
}

# ── Restore both volumes ──────────────────────────────────────────────────────
echo "[restore] Project:  ${COMPOSE_PROJECT}"
echo "[restore] Source:   ${BACKUP_DIR}"
echo ""

restore_volume "${PRIMARY_VOLUME}"
restore_volume "${REPLICA_VOLUME}"

echo ""
echo "[restore] Restore complete. You may now restart the containers:"
echo "          docker compose start postgres-primary postgres-replica"
