-- sandbox_read_user.sql
-- Creates the sandbox-read role with read-only access to the fin_markets schema.
--
-- Run this on the PRIMARY; DDL and GRANTs replicate automatically to the replica.
-- The sandbox-runner containers connect to postgres-REPLICA using these credentials.
--
-- Default password matches SANDBOX_PG_READ_PASSWORD in docker-compose.yml.
-- Change both together for production deployments.
--
-- Usage:
--   psql -U admin -d fin_trading -f sql/postgres/primary/sandbox_read_user.sql

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'sandbox-read') THEN
        CREATE USER "sandbox-read" WITH
            PASSWORD 'SandboxRd@2026'
            NOSUPERUSER
            NOCREATEDB
            NOCREATEROLE
            LOGIN;
    END IF;
END
$$;

-- Allow the role to connect to the application database.
GRANT CONNECT ON DATABASE fin_trading TO "sandbox-read";

-- Allow schema introspection (required for psycopg to resolve table metadata).
GRANT USAGE ON SCHEMA fin_markets TO "sandbox-read";

-- Read access to all current tables in fin_markets.
GRANT SELECT ON ALL TABLES IN SCHEMA fin_markets TO "sandbox-read";

-- Ensure future tables created in fin_markets are automatically readable.
ALTER DEFAULT PRIVILEGES IN SCHEMA fin_markets
    GRANT SELECT ON TABLES TO "sandbox-read";
