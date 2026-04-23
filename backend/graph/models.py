"""ORM models for graph node execution records, agent sub-tasks, and task step audit log."""

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP as PG_TIMESTAMPTZ
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.postgres.base import Base
from backend.db.postgres.types import QueryStatus, query_status_sa_type, StreamingStatus, streaming_status_sa_type


class NodeExecution(Base):
    """One row per node invocation; records input state, output, and wall-clock time."""

    __tablename__ = "node_executions"

    __table_args__ = (
        Index("fin_agents_node_executions_thread_id_idx", "thread_id"),
        Index("fin_agents_node_executions_node_name_idx", "node_name"),
        {"schema": "fin_agents"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    thread_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("fin_agents.user_queries.thread_id", ondelete="CASCADE"),
        nullable=False,
    )

    node_name: Mapped[str] = mapped_column(String, nullable=False)

    input: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    started_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False)
    elapsed_ms: Mapped[int] = mapped_column(Integer, nullable=False)


class AgentTask(Base):
    """One row per agent sub-task within a node execution.

    Used for fine-grained tracking of individual fetches and LLM calls
    so they can be streamed to the client via SSE.
    """

    __tablename__ = "tasks"

    __table_args__ = (
        Index("fin_agents_tasks_thread_id_idx", "thread_id"),
        Index("fin_agents_tasks_node_name_idx", "node_name"),
        Index("fin_agents_tasks_node_execution_id_idx", "node_execution_id"),
        {"schema": "fin_agents"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

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
    task_key: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(query_status_sa_type, nullable=False, default=QueryStatus.RUNNING)
    input: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )


class Streaming(Base):
    """One row per task status transition — lightweight audit trail for task lifecycle.

    Records only timing and status metadata; never stores query text, tokens,
    or I/O payloads.  A new row is appended by each lifecycle function
    (``create_task``, ``complete_task``, ``fail_task``, ``cancel_task``) so the
    history of every task can be reconstructed from this table.
    """

    __tablename__ = "streamings"

    __table_args__ = (
        Index("fin_agents_streamings_task_id_idx", "task_id"),
        Index("fin_agents_streamings_thread_id_idx", "thread_id"),
        {"schema": "fin_agents"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    task_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("fin_agents.tasks.id", ondelete="CASCADE"),
        nullable=False,
    )

    thread_id: Mapped[str] = mapped_column(
        String,
        ForeignKey("fin_agents.user_queries.thread_id", ondelete="CASCADE"),
        nullable=False,
    )

    #: Status the task transitioned INTO at this step.
    status: Mapped[str] = mapped_column(streaming_status_sa_type, nullable=False)

    #: True once the SSE generator confirmed delivery to the client.
    is_ack: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="FALSE")

    #: Wall-clock timestamp when the ack was recorded.
    ack_at: Mapped[Optional[datetime]] = mapped_column(
        PG_TIMESTAMPTZ(timezone=True),
        nullable=True,
    )

    #: Number of times the pg_notify was re-sent before the client acked.
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        PG_TIMESTAMPTZ(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
