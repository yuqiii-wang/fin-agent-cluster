CREATE SCHEMA IF NOT EXISTS fin_agents;

CREATE TYPE fin_agents.query_status AS ENUM ('received', 'pending', 'running', 'completed', 'failed', 'cancelled');


CREATE TABLE IF NOT EXISTS fin_agents.user_queries (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL UNIQUE,
    user_id TEXT,
    query TEXT NOT NULL,
    answer TEXT,
    status fin_agents.query_status NOT NULL DEFAULT 'pending',
    is_ack      BOOLEAN NOT NULL DEFAULT FALSE,
    extra JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error TEXT
);

CREATE INDEX IF NOT EXISTS fin_agents_user_queries_user_id_idx ON fin_agents.user_queries (user_id);
CREATE INDEX IF NOT EXISTS fin_agents_user_queries_status_idx ON fin_agents.user_queries (status);
CREATE INDEX IF NOT EXISTS fin_agents_user_queries_created_at_idx ON fin_agents.user_queries (created_at DESC);

-- Dedup guard: prevent concurrent submissions of the same query by the same user.
-- A duplicate INSERT from a second FastAPI instance raises UniqueViolation which the
-- application converts to a NACK (status='cancelled') returning the existing thread_id.
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_queries_dedup
    ON fin_agents.user_queries (user_id, md5(query))
    WHERE status IN ('received', 'pending', 'running');

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


-- Sub-tasks emitted by each graph node (one row per fetch / LLM call)
CREATE TABLE IF NOT EXISTS fin_agents.tasks (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES fin_agents.user_queries (thread_id) ON DELETE CASCADE,
    node_execution_id BIGINT REFERENCES fin_agents.node_executions (id) ON DELETE CASCADE,
    node_name TEXT NOT NULL,
    task_key  TEXT NOT NULL,
    status    fin_agents.query_status NOT NULL DEFAULT 'pending',
    input     JSONB NOT NULL DEFAULT '{}',
    output    JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS fin_agents_tasks_node_execution_id_idx ON fin_agents.tasks (node_execution_id);

CREATE INDEX IF NOT EXISTS fin_agents_tasks_thread_id_idx ON fin_agents.tasks (thread_id);
CREATE INDEX IF NOT EXISTS fin_agents_tasks_node_name_idx ON fin_agents.tasks (node_name);

-- LLM token usage records persisted by the FastAPI background task
-- from the fin:llm:completions Redis Stream after each celery-ingest invocation.
CREATE TABLE IF NOT EXISTS fin_agents.llm_responses (
    id                BIGSERIAL PRIMARY KEY,
    event_id          TEXT NOT NULL UNIQUE,
    ts                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    thread_id         TEXT,
    provider          TEXT NOT NULL DEFAULT '',
    model             TEXT NOT NULL DEFAULT '',
    task_key          TEXT,
    node_name         TEXT,
    prompt_tokens     INT NOT NULL DEFAULT 0,
    prompts           TEXT,
    thinking          TEXT,
    answer            TEXT,
    completion_tokens INT NOT NULL DEFAULT 0,
    total_tokens      INT NOT NULL DEFAULT 0,
    latency_ms        INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS fin_agents_llm_responses_thread_id_idx ON fin_agents.llm_responses (thread_id);
CREATE INDEX IF NOT EXISTS fin_agents_llm_responses_ts_idx ON fin_agents.llm_responses (ts DESC);
CREATE INDEX IF NOT EXISTS fin_agents_llm_responses_provider_model_idx ON fin_agents.llm_responses (provider, model);

