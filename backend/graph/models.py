"""ORM models for graph node execution records and agent sub-tasks."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, TIMESTAMP, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.postgres.base import Base


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
    status: Mapped[str] = mapped_column(String, nullable=False, default="running")
    input: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    output: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )
