"""ORM model for user-submitted queries."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, CheckConstraint, Index, String, Text, func, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.base import Base


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
