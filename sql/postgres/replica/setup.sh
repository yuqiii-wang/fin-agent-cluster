#!/bin/bash
# Replica entrypoint: waits for the primary, runs pg_basebackup on first start,
# then hands off to the standard docker-entrypoint.sh to start postgres.
set -e

PRIMARY_HOST="${PRIMARY_HOST:-postgres-primary}"
PRIMARY_PORT="${PRIMARY_PORT:-5432}"
REPL_USER="${POSTGRES_REPLICATION_USER:-replicator}"
REPL_PASS="${POSTGRES_REPLICATION_PASSWORD:-replpassword}"
PGDATA="${PGDATA:-/var/lib/postgresql/18/docker}"
PG_HOME="/var/lib/postgresql"

# Ensure PGDATA and its parent dirs exist and are owned by the postgres user.
# Running as root (user: root in compose) so we can mkdir and chown freely.
mkdir -p "$PGDATA"
chown -R postgres:postgres "$PG_HOME"

# Write .pgpass to the postgres user's home so both basebackup and streaming
# replication can authenticate without a password prompt.
PGPASS_FILE="$PG_HOME/.pgpass"
cat > "${PGPASS_FILE}" <<-EOF
${PRIMARY_HOST}:${PRIMARY_PORT}:replication:${REPL_USER}:${REPL_PASS}
*:*:*:${REPL_USER}:${REPL_PASS}
EOF
chmod 600 "${PGPASS_FILE}"
chown postgres:postgres "${PGPASS_FILE}"

# ── Wait for primary ──────────────────────────────────────────────────────────
echo "[replica] Waiting for primary at ${PRIMARY_HOST}:${PRIMARY_PORT}..."
until PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_isready \
        -h "${PRIMARY_HOST}" \
        -p "${PRIMARY_PORT}" \
        -U "${POSTGRES_USER:-admin}"; do
    sleep 2
done
echo "[replica] Primary is ready."

# ── Bootstrap from primary (first start only) ────────────────────────────────
if [ ! -f "${PGDATA}/PG_VERSION" ]; then
    echo "[replica] Running pg_basebackup to initialise data directory..."
    # Remove any partial state before a clean basebackup.
    rm -rf "${PGDATA:?}/"*

    PGPASSWORD="${REPL_PASS}" gosu postgres pg_basebackup \
        -h "${PRIMARY_HOST}" \
        -p "${PRIMARY_PORT}" \
        -U "${REPL_USER}" \
        -D "${PGDATA}" \
        --wal-method=stream \
        --checkpoint=fast \
        --write-recovery-conf \
        --progress \
        --verbose

    # pg_basebackup --write-recovery-conf creates standby.signal and sets
    # primary_conninfo in postgresql.auto.conf.  Append the password so
    # postgres can reconnect after restart without relying solely on .pgpass.
    {
        echo ""
        echo "# Password injected by replica/setup.sh"
        echo "primary_conninfo = 'host=${PRIMARY_HOST} port=${PRIMARY_PORT} user=${REPL_USER} password=${REPL_PASS} sslmode=prefer'"
    } >> "${PGDATA}/postgresql.auto.conf"

    # Ensure standby mode is signalled.
    touch "${PGDATA}/standby.signal"

    echo "[replica] pg_basebackup complete — standby configured."
fi

# ── Ensure replica GUCs are compatible with the primary ──────────────────────
# pg_basebackup does not copy command-line -c overrides from the primary.
# The replica must have max_connections >= primary (300) or recovery aborts.
# Write unconditionally so this also applies on container restarts.
{
    echo ""
    echo "# GUCs injected by replica/setup.sh to match primary settings"
    echo "max_connections = 300"
} >> "${PGDATA}/postgresql.auto.conf"

# ── Delegate to the standard postgres entrypoint ─────────────────────────────
# docker-entrypoint.sh finds PG_VERSION, skips initdb, and starts postgres.
# Run as root so docker-entrypoint.sh can do its own permission fixups.
exec /usr/local/bin/docker-entrypoint.sh postgres
