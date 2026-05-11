#!/bin/bash
# Runs inside the primary container via docker-entrypoint-initdb.d.
# Creates the replication role and enables WAL streaming so the replica
# can connect via pg_basebackup / streaming replication.
set -e

REPL_USER="${POSTGRES_REPLICATION_USER:-replicator}"
REPL_PASS="${POSTGRES_REPLICATION_PASSWORD:-replpassword}"

# Create the replication role if it does not already exist.
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres <<-EOSQL
    DO \$\$
    BEGIN
        IF NOT EXISTS (
            SELECT FROM pg_catalog.pg_roles WHERE rolname = '${REPL_USER}'
        ) THEN
            CREATE USER ${REPL_USER}
                WITH REPLICATION
                ENCRYPTED PASSWORD '${REPL_PASS}';
        END IF;
    END
    \$\$;
EOSQL

# Append replication settings to postgresql.conf.
# docker-entrypoint.sh stops the temporary server and restarts it with the
# final command, so these settings take effect at the next (normal) start.
cat >> "${PGDATA}/postgresql.conf" <<-EOF

# ── Streaming replication (added by init-replication.sh) ────────────────────
wal_level = replica
max_wal_senders = 10
wal_keep_size = 128
hot_standby = on
EOF

# Allow the replication user to connect from any Docker-internal host.
cat >> "${PGDATA}/pg_hba.conf" <<-EOF

# Replication connections (added by init-replication.sh)
host    replication    ${REPL_USER}    all    scram-sha-256
EOF

echo "[init-replication] primary configured: replication user '${REPL_USER}', WAL streaming enabled."
