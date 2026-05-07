"""ORM models for graph node execution records and agent sub-tasks."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.postgres.base import Base
from backend.db.postgres.types import QueryStatus, query_status_sa_type


class Node(Base):
    """Per-thread node identity registry — one row per unique node_id (UUID) per thread.

    Tracks the node's type classification (Typical / Reference / Subgraph) and
    the most-recent execution reference.  Rows are created on-first-seen and
    updated via ``INSERT … ON CONFLICT DO UPDATE`` from
    :func:`~backend.graph.utils.execution_log.upsert_node_record`.

    Distinct from :class:`NodeExecution` which logs every individual run:
    a node can execute many times (loops) but has exactly one ``nodes`` row
    per thread that carries its current status and type metadata.
    """

    __tablename__ = "nodes"

    __table_args__ = (
        Index("fin_agents_nodes_thread_id_idx", "thread_id"),
        Index("fin_agents_nodes_node_name_thread_id_idx", "node_name", "thread_id"),
        Index(
            "fin_agents_nodes_referenced_node_id_idx",
            "referenced_node_id",
            postgresql_where="referenced_node_id IS NOT NULL",
        ),
        {"schema": "fin_agents"},
    )

    # Governance UUID generated at node invocation time (matches node_executions.node_uuid).
    node_id: Mapped[str] = mapped_column(String, primary_key=True)

    thread_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("fin_agents.user_queries.thread_id", ondelete="CASCADE"),
        nullable=False,
    )

    node_name: Mapped[str] = mapped_column(String, nullable=False)

    # Node type: 'Typical' (default), 'Subgraph' (compiled sub-graph),
    # or 'Reference' (pointer to another node).
    type: Mapped[str] = mapped_column(String, nullable=False, default="Typical")

    # For Reference nodes: the target node_id within the same thread.
    # NULL for Typical and Subgraph nodes.
    referenced_node_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("fin_agents.nodes.node_id", ondelete="SET NULL"),
        nullable=True,
    )

    last_status: Mapped[Optional[str]] = mapped_column(query_status_sa_type, nullable=True)
    last_node_execution_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("fin_agents.node_executions.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_executed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )


class NodeExecution(Base):
    """One row per node invocation; records input state, output, and wall-clock time.

    ``node_uuid`` links this DB row to the Redis governance registry so that
    cancel/status signals can be scoped to a specific node execution.
    ``status`` reflects the node's lifecycle — 'running' on insert, updated to
    'completed', 'failed', or 'cancelled' when the node terminates.
    ``parent_node_execution_id`` is set for inner subgraph nodes to point at
    their enclosing outer node execution, enabling the full nesting hierarchy:
    thread → outer_node → inner_node → task.
    """

    __tablename__ = "node_executions"

    __table_args__ = (
        Index("fin_agents_node_executions_thread_id_idx", "thread_id"),
        Index("fin_agents_node_executions_node_name_idx", "node_name"),
        Index("fin_agents_node_executions_parent_idx", "parent_node_execution_id",
              postgresql_where="parent_node_execution_id IS NOT NULL"),
        Index("fin_agents_node_executions_node_uuid_idx", "node_uuid",
              postgresql_where="node_uuid IS NOT NULL"),
        {"schema": "fin_agents"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    thread_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("fin_agents.user_queries.thread_id", ondelete="CASCADE"),
        nullable=False,
    )

    # NULL for top-level graph nodes; set for inner subgraph / nested nodes.
    parent_node_execution_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("fin_agents.node_executions.id", ondelete="CASCADE"),
        nullable=True,
    )

    node_name: Mapped[str] = mapped_column(String, nullable=False)

    # Governance UUID matching the in-memory node_id generated at runtime.
    # Used to correlate Redis governance registry entries with PG rows.
    node_uuid: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Lifecycle status — updated as the node progresses.
    status: Mapped[str] = mapped_column(
        query_status_sa_type, nullable=False, default=QueryStatus.RUNNING
    )

    input: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    started_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)


class AgentTask(Base):
    """One row per agent sub-task within a node execution.

    Used for fine-grained tracking of individual fetches and LLM calls
    so they can be streamed to the client via SSE.

    ``task_id`` links this DB row to the Redis governance task entry so that
    cancel/status signals and stream registrations can be correlated.
    """

    __tablename__ = "tasks"

    __table_args__ = (
        Index("fin_agents_tasks_thread_id_idx", "thread_id"),
        Index("fin_agents_tasks_node_name_idx", "node_name"),
        Index("fin_agents_tasks_node_execution_id_idx", "node_execution_id"),
        {"schema": "fin_agents"},
    )

    # task_id is the primary key — the governance UUID generated in-node.
    task_id: Mapped[str] = mapped_column(String, primary_key=True)

    thread_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("fin_agents.user_queries.thread_id", ondelete="CASCADE"),
        nullable=False,
    )

    node_execution_id: Mapped[Optional[int]] = mapped_column(
        BigInteger,
        ForeignKey("fin_agents.node_executions.id", ondelete="CASCADE"),
        nullable=True,
    )

    node_name: Mapped[str] = mapped_column(String, nullable=False)
    task_name: Mapped[str] = mapped_column(String, nullable=False)

    # task_id is the PK — remove the separate Optional task_id column.

    status: Mapped[str] = mapped_column(query_status_sa_type, nullable=False, default=QueryStatus.RUNNING)
    input: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )


class LlmResponse(Base):
    """One LLM completion record persisted from ``fin:llm:completions`` Redis Stream.

    ``task_id`` is the optional 1:1 link to the ``fin_agents.tasks`` row that
    triggered this LLM call.  Set when the celery ingest worker carries a
    ``task_id`` from :func:`~backend.sse_notifications.agent_tasks.lifecycle.create_task`.
    """

    __tablename__ = "llm_responses"

    __table_args__ = (
        Index("fin_agents_llm_responses_thread_id_idx", "thread_id"),
        Index("fin_agents_llm_responses_ts_idx", "ts"),
        Index("fin_agents_llm_responses_provider_model_idx", "provider", "model"),
        Index("fin_agents_llm_responses_task_id_idx", "task_id",
              postgresql_where="task_id IS NOT NULL"),
        {"schema": "fin_agents"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    ts: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=func.now())
    thread_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    # Optional 1:1 FK to fin_agents.tasks — present when the LLM ingest
    # worker received a task_id from the calling node.
    task_id: Mapped[Optional[str]] = mapped_column(
        String,
        ForeignKey("fin_agents.tasks.task_id", ondelete="SET NULL"),
        nullable=True,
    )

    provider: Mapped[str] = mapped_column(String, nullable=False, default="")
    model: Mapped[str] = mapped_column(String, nullable=False, default="")
    task_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    node_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompts: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    thinking: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    answer: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
