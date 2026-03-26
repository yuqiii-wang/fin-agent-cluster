"""SQLAlchemy ORM models for application-owned tables."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Integer, String, Text, func, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UserQuery(Base):
    """One row per user request; thread_id is the LangGraph correlation key."""

    __tablename__ = "user_queries"

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_user_queries_status",
        ),
        Index("fin_agents_user_queries_user_id_idx", "user_id"),
        Index("fin_agents_user_queries_status_idx", "status"),
        Index("fin_agents_user_queries_created_at_idx", "created_at"),
        {"schema": "fin_agents"},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)

    # UUID assigned at request time; used as the LangGraph thread_id
    thread_id: Mapped[str] = mapped_column(String, nullable=False, unique=True)

    user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    query: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(String, nullable=False, default="pending")

    answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)

    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


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
