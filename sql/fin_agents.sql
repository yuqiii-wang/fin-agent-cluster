CREATE SCHEMA IF NOT EXISTS fin_agents;

-- Drop and recreate ENUMs so schema changes (added/removed values) are always applied.
DROP TYPE IF EXISTS fin_agents.query_status CASCADE;
CREATE TYPE fin_agents.query_status AS ENUM ('connecting', 'received', 'running', 'completed', 'failed', 'cancelled');

DROP TYPE IF EXISTS fin_agents.work_status CASCADE;
CREATE TYPE fin_agents.work_status AS ENUM ('pending', 'running', 'completed', 'failed', 'cancelled', 'wrong');

DROP TYPE IF EXISTS fin_agents.node_types CASCADE;
CREATE TYPE fin_agents.node_types AS ENUM ('Workflow', 'Subgraph');

DROP TYPE IF EXISTS fin_agents.task_types CASCADE;
CREATE TYPE fin_agents.task_types AS ENUM ('Streaming', 'WebRequest', 'Computation', 'ToolCall');


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



-- Dedup guard — same-minute resubmission guard.
-- Blocks the same user from resubmitting the identical query within the same
-- calendar minute, even after a previous attempt completed or failed.
-- Uses an immutable expression so it works as a unique index predicate.
CREATE UNIQUE INDEX IF NOT EXISTS uq_user_queries_time_guard
    ON fin_agents.user_queries (user_id, md5(query), date_trunc('minute', created_at AT TIME ZONE 'UTC'));

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
    node_id             TEXT NOT NULL PRIMARY KEY,
    thread_id           TEXT NOT NULL REFERENCES fin_agents.user_queries (thread_id) ON DELETE CASCADE,
    -- Fork generation: 0 = original run, 1+ = re-explore branches.
    -- UUID5(thread_id:node_name:v{version}) determines node_id deterministically.
    version             INTEGER NOT NULL DEFAULT 0,
    type                fin_agents.node_types NOT NULL DEFAULT 'Workflow',
    -- Self-referencing FK: set for inner subgraph nodes whose parent is an outer
    -- subgraph node.  NULL for top-level graph nodes.
    parent_node_id      TEXT REFERENCES fin_agents.nodes (node_id) ON DELETE CASCADE,
    node_name           TEXT NOT NULL,
    -- Identifies nodes that execute concurrently within the same parent graph or subgraph.
    parallel_group      TEXT,
    -- Identifies the branch within a parallel_group for sequential chains.
    -- NULL for non-parallel nodes.  Defaults to node_name for single-node branches.
    -- All nodes in the same sequential chain share the same parallel_branch value.
    parallel_branch     TEXT,
    -- Latest node_ids from sibling parallel branches at the last known snapshot time.
    -- Shape: {branch_key: node_id}.  Retroactively updated as sibling branches advance.
    parallel_snapshots  JSONB NOT NULL DEFAULT '{}',
    status              fin_agents.work_status NOT NULL DEFAULT 'pending',
    -- LangGraph checkpoint_id that was active when this node started.
    checkpoint_id       TEXT NOT NULL DEFAULT '',
    -- DAG edges within this run's branch: IDs of predecessor/successor nodes.
    prev_node_ids       TEXT[] NOT NULL DEFAULT '{}',
    next_node_ids       TEXT[] NOT NULL DEFAULT '{}',
    -- Task UUIDs spawned by this node (appended as tasks are created).
    task_ids            TEXT[] NOT NULL DEFAULT '{}',
    -- Indicates whether this node is the fork-point of a re-explore branch.
    -- One is_forked=TRUE node per version > 0.  Original run (version=0) has none.
    is_forked           BOOLEAN NOT NULL DEFAULT FALSE,
    -- The version that this fork branched from.  NULL for version=0 nodes.
    -- For the is_forked node: equals the source node's version at fork time.
    -- For non-forked nodes within the same version: also set to the source version
    -- so the API can return the full branch lineage without extra joins.
    forked_from_version INTEGER,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    elapsed_ms          INTEGER NOT NULL DEFAULT 0,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Fencing token from the Redis per-thread counter at lock acquisition time.
    -- Zombie writes (lower token) are rejected by guards in upsert/complete SQL.
    fencing_token       BIGINT NOT NULL DEFAULT 0,
    -- (thread_id, node_name, version) uniquely identifies each fork branch.
    UNIQUE (thread_id, node_name, version)
);

CREATE INDEX IF NOT EXISTS fin_agents_nodes_thread_id_idx ON fin_agents.nodes (thread_id);
CREATE INDEX IF NOT EXISTS fin_agents_nodes_node_name_idx ON fin_agents.nodes (node_name);
CREATE INDEX IF NOT EXISTS fin_agents_nodes_node_name_thread_id_idx ON fin_agents.nodes (node_name, thread_id);

CREATE INDEX IF NOT EXISTS fin_agents_nodes_parallel_group_idx
    ON fin_agents.nodes (thread_id, parallel_group, parent_node_id, parallel_branch)
    WHERE parallel_group IS NOT NULL AND parallel_branch IS NOT NULL;

-- Stores actual input/output payloads for node executions, separated from topology.
-- Downstream nodes read completed predecessors' output via the PG replica.
CREATE TABLE IF NOT EXISTS fin_agents.node_executions (
    node_id     TEXT NOT NULL PRIMARY KEY
                REFERENCES fin_agents.nodes (node_id) ON DELETE CASCADE,
    input       JSONB NOT NULL DEFAULT '{}',
    output      JSONB NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Sub-tasks emitted by each graph node (one row per fetch / LLM call).
-- task_id is the primary key — the governance UUID generated in-node,
-- eliminating the dual-identity problem of having both a numeric id and a uuid.
CREATE TABLE IF NOT EXISTS fin_agents.tasks (
    task_id       TEXT NOT NULL PRIMARY KEY,
    thread_id     TEXT NOT NULL REFERENCES fin_agents.user_queries (thread_id) ON DELETE CASCADE,
    node_id       TEXT REFERENCES fin_agents.nodes (node_id) ON DELETE CASCADE,
    node_name     TEXT NOT NULL,
    task_name     TEXT NOT NULL,
    type          fin_agents.task_types NOT NULL DEFAULT 'ToolCall',
    status        fin_agents.work_status NOT NULL DEFAULT 'pending',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Fencing token matching the graph run that created this task.
    -- Used by cleanup_zombie_tasks to mark orphaned tasks as 'wrong'.
    -- 0 = pre-fencing rows.
    fencing_token BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS fin_agents_tasks_node_id_idx ON fin_agents.tasks (node_id);
CREATE INDEX IF NOT EXISTS fin_agents_tasks_thread_id_idx ON fin_agents.tasks (thread_id);
CREATE INDEX IF NOT EXISTS fin_agents_tasks_node_name_idx ON fin_agents.tasks (node_name);

-- Stores actual input/output payloads for task executions, separated from metadata.
CREATE TABLE IF NOT EXISTS fin_agents.task_executions (
    task_id     TEXT NOT NULL PRIMARY KEY
                REFERENCES fin_agents.tasks (task_id) ON DELETE CASCADE,
    input       JSONB NOT NULL DEFAULT '{}',
    output      JSONB NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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

