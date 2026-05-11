CREATE SCHEMA IF NOT EXISTS fin_agents;

-- Drop and recreate ENUMs so schema changes (added/removed values) are always applied.
DROP TYPE IF EXISTS fin_agents.query_status CASCADE;
CREATE TYPE fin_agents.query_status AS ENUM ('connecting', 'received', 'running', 'completed', 'failed', 'cancelled');

DROP TYPE IF EXISTS fin_agents.work_status CASCADE;
CREATE TYPE fin_agents.work_status AS ENUM ('pending', 'running', 'completed', 'failed', 'cancelled', 'wrong');

DROP TYPE IF EXISTS fin_agents.node_types CASCADE;
CREATE TYPE fin_agents.node_types AS ENUM ('Typical', 'Reference', 'Subgraph');


CREATE TABLE IF NOT EXISTS fin_agents.user_queries (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT NOT NULL UNIQUE,
    user_id TEXT,
    query TEXT NOT NULL,
    answer TEXT,
    status fin_agents.query_status NOT NULL DEFAULT 'connecting',
    is_ack      BOOLEAN NOT NULL DEFAULT FALSE,
    extra JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    error TEXT
);

CREATE INDEX IF NOT EXISTS fin_agents_user_queries_user_id_idx ON fin_agents.user_queries (user_id);
CREATE INDEX IF NOT EXISTS fin_agents_user_queries_created_at_idx ON fin_agents.user_queries (created_at DESC);



-- Dedup guard — same-second resubmission guard.
-- Blocks the same user from resubmitting the identical query within the same
-- calendar second, even after a previous attempt completed or failed.
-- Uses an immutable expression so it works as a unique index predicate.
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_queries_time_guard
    ON fin_agents.user_queries (user_id, md5(query), date_trunc('second', created_at AT TIME ZONE 'UTC'));

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

CREATE TABLE IF NOT EXISTS fin_agents.nodes (
    node_id          TEXT NOT NULL PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES fin_agents.user_queries (thread_id) ON DELETE CASCADE,
    type             fin_agents.node_types NOT NULL DEFAULT 'Typical',
    -- Self-referencing FK: set for inner subgraph nodes whose parent is an outer
    -- subgraph node.  NULL for top-level graph nodes.
    parent_node_id  TEXT REFERENCES fin_agents.nodes (node_id) ON DELETE CASCADE,
    -- For Reference nodes: the target node_id within the same thread.
    -- NULL for Typical and Subgraph nodes.
    referenced_node_id TEXT REFERENCES fin_agents.nodes (node_id) ON DELETE SET NULL,
    node_name TEXT NOT NULL,
    status    fin_agents.work_status NOT NULL DEFAULT 'pending',
    input JSONB NOT NULL DEFAULT '{}',
    output JSONB NOT NULL DEFAULT '{}',
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    elapsed_ms INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS fin_agents_nodes_thread_id_idx ON fin_agents.nodes (thread_id);
CREATE INDEX IF NOT EXISTS fin_agents_nodes_node_name_idx ON fin_agents.nodes (node_name);
CREATE INDEX IF NOT EXISTS fin_agents_nodes_node_name_thread_id_idx ON fin_agents.nodes (node_name, thread_id);
CREATE INDEX IF NOT EXISTS fin_agents_nodes_referenced_node_id_idx ON fin_agents.nodes (referenced_node_id)
    WHERE referenced_node_id IS NOT NULL;

-- Sub-tasks emitted by each graph node (one row per fetch / LLM call).
-- task_id is the primary key — the governance UUID generated in-node,
-- eliminating the dual-identity problem of having both a numeric id and a uuid.
CREATE TABLE IF NOT EXISTS fin_agents.tasks (
    task_id TEXT NOT NULL PRIMARY KEY,
    thread_id TEXT NOT NULL REFERENCES fin_agents.user_queries (thread_id) ON DELETE CASCADE,
    node_id TEXT REFERENCES fin_agents.nodes (node_id) ON DELETE CASCADE,
    node_name TEXT NOT NULL,
    task_name  TEXT NOT NULL,
    status    fin_agents.work_status NOT NULL DEFAULT 'pending',
    input     JSONB NOT NULL DEFAULT '{}',
    output    JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS fin_agents_tasks_node_id_idx ON fin_agents.tasks (node_id);
CREATE INDEX IF NOT EXISTS fin_agents_tasks_thread_id_idx ON fin_agents.tasks (thread_id);
CREATE INDEX IF NOT EXISTS fin_agents_tasks_node_name_idx ON fin_agents.tasks (node_name);

-- LLM token usage records persisted by the FastAPI background task
-- from the fin:llm:completions Redis Stream after each celery-ingest invocation.
CREATE TABLE IF NOT EXISTS fin_agents.llm_responses (
    id                BIGSERIAL PRIMARY KEY,
    event_id          TEXT NOT NULL UNIQUE,
    ts                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    thread_id         TEXT,
    -- Optional 1:1 link to the tasks row that produced this LLM call.
    -- Set when the LLM ingest worker carries a task_id from create_task().
    task_id         TEXT REFERENCES fin_agents.tasks (task_id) ON DELETE SET NULL,
    provider          TEXT NOT NULL DEFAULT '',
    model             TEXT NOT NULL DEFAULT '',
    task_name          TEXT,
    node_name         TEXT,
    input_tokens     INT NOT NULL DEFAULT 0,
    prompts           TEXT,
    thinking          TEXT,
    answer            TEXT,
    output_tokens    INT NOT NULL DEFAULT 0,
    total_tokens      INT NOT NULL DEFAULT 0,
    latency_ms        INT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS fin_agents_llm_responses_thread_id_idx ON fin_agents.llm_responses (thread_id);
CREATE INDEX IF NOT EXISTS fin_agents_llm_responses_ts_idx ON fin_agents.llm_responses (ts DESC);
CREATE INDEX IF NOT EXISTS fin_agents_llm_responses_provider_model_idx ON fin_agents.llm_responses (provider, model);
CREATE INDEX IF NOT EXISTS fin_agents_llm_responses_task_id_idx ON fin_agents.llm_responses (task_id)
    WHERE task_id IS NOT NULL;

