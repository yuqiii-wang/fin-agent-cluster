#!/bin/bash
# backup.sh — Copy Docker volume data for postgres-primary and postgres-replica
# out to a timestamped directory under pg-backup/.
#
# Usage: ./backup.sh [--dest <path>]
#   --dest  Destination directory  (default: <project-root>/pg-backup)
#
# Docker named volumes live at /var/lib/docker/volumes/<name>/_data on the host.
# This script copies those directories directly — no container required.

set -euo pipefail

DOCKER_VOLUMES_ROOT="/var/lib/docker/volumes"

# ── Resolve project root (three levels up: replica → postgres → sql → root) ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"

# ── Parse arguments ───────────────────────────────────────────────────────────
DEST="${PROJECT_ROOT}/pg-backup"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --dest)
            DEST="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 1
            ;;
    esac
done

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_DIR="${DEST}/${TIMESTAMP}"
mkdir -p "${BACKUP_DIR}"

# ── Detect compose project name ───────────────────────────────────────────────
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-$(basename "${PROJECT_ROOT}" | tr '[:upper:]' '[:lower:]')}"

PRIMARY_VOLUME="${COMPOSE_PROJECT}_postgres_primary_data"
REPLICA_VOLUME="${COMPOSE_PROJECT}_postgres_replica_data"

# ── Helper: copy one volume's _data directory ─────────────────────────────────
backup_volume() {
    local volume_name="$1"
    local src="${DOCKER_VOLUMES_ROOT}/${volume_name}/_data"
    local dst="${BACKUP_DIR}/${volume_name}"

    if [[ ! -d "${src}" ]]; then
        echo "[backup] WARNING: '${src}' not found — skipping." >&2
        return 0
    fi

    echo "[backup] Copying ${src} → ${dst}"
    cp -a "${src}" "${dst}"

    local size
    size="$(du -sh "${dst}" | cut -f1)"
    echo "[backup] Done: ${dst} (${size})"
}

# ── Back up both volumes ──────────────────────────────────────────────────────
echo "[backup] Project: ${COMPOSE_PROJECT}"
echo "[backup] Destination: ${BACKUP_DIR}"
echo ""

backup_volume "${PRIMARY_VOLUME}"
backup_volume "${REPLICA_VOLUME}"

echo ""
echo "[backup] Backup complete: ${BACKUP_DIR}"
