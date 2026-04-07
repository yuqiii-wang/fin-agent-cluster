CREATE SCHEMA IF NOT EXISTS fin_agents;

CREATE TABLE IF NOT EXISTS fin_agents.user_queries (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL UNIQUE,
    user_id TEXT,
    query TEXT NOT NULL,
    answer TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    extra JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error TEXT
);

CREATE INDEX IF NOT EXISTS fin_agents_user_queries_user_id_idx ON fin_agents.user_queries (user_id);
CREATE INDEX IF NOT EXISTS fin_agents_user_queries_status_idx ON fin_agents.user_queries (status);
CREATE INDEX IF NOT EXISTS fin_agents_user_queries_created_at_idx ON fin_agents.user_queries (created_at DESC);

CREATE TABLE IF NOT EXISTS fin_agents.checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id),
    FOREIGN KEY (thread_id) REFERENCES fin_agents.user_queries (thread_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS fin_agents.checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version),
    FOREIGN KEY (thread_id) REFERENCES fin_agents.user_queries (thread_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

CREATE TABLE IF NOT EXISTS fin_agents.checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    task_path TEXT NOT NULL DEFAULT '',
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    blob BYTEA NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx),
    FOREIGN KEY (thread_id) REFERENCES fin_agents.user_queries (thread_id) ON DELETE CASCADE DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx ON fin_agents.checkpoints (thread_id);
CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx ON fin_agents.checkpoint_blobs (thread_id);
CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx ON fin_agents.checkpoint_writes (thread_id);

CREATE TABLE IF NOT EXISTS fin_agents.node_executions (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES fin_agents.user_queries (thread_id) ON DELETE CASCADE,
    node_name TEXT NOT NULL,
    input JSONB NOT NULL DEFAULT '{}',
    output JSONB NOT NULL DEFAULT '{}',
    started_at TIMESTAMPTZ NOT NULL,
    elapsed_ms INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS fin_agents_node_executions_thread_id_idx ON fin_agents.node_executions (thread_id);
CREATE INDEX IF NOT EXISTS fin_agents_node_executions_node_name_idx ON fin_agents.node_executions (node_name);

-- external_resources: logs every call to an external API (quant data providers, web search, etc.)
-- used as a 1-hour cache in DEBUG mode — same cache_key within the TTL returns the stored output
-- thread_id is nullable so the same cached record can be reused across different threads
CREATE TABLE IF NOT EXISTS fin_agents.external_resources (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT REFERENCES fin_agents.user_queries (thread_id) ON DELETE SET NULL,
    node_name TEXT NOT NULL DEFAULT 'unknown',
    source TEXT NOT NULL,          -- provider/client name: 'fmp', 'yfinance', 'web_search', etc.
    method TEXT NOT NULL,          -- method/endpoint name: 'get_company_profile', etc.
    cache_key TEXT NOT NULL,       -- sha256(source + method + serialised input) for cache lookup
    input JSONB NOT NULL DEFAULT '{}',
    output JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS fin_agents_external_resources_cache_key_idx
    ON fin_agents.external_resources (cache_key, created_at DESC);
CREATE INDEX IF NOT EXISTS fin_agents_external_resources_thread_id_idx
    ON fin_agents.external_resources (thread_id);
CREATE INDEX IF NOT EXISTS fin_agents_external_resources_source_method_idx
    ON fin_agents.external_resources (source, method);
