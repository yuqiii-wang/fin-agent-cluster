"""backend.users.models -- SQLAlchemy ORM models for user and query tables."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.postgres.base import Base
from backend.db.postgres.types import query_status_sa_type


class GuestUser(Base):
    """ORM model for ``fin_users.users``.

    Supports guest, password, and future OAuth accounts.
    """

    __tablename__ = "users"
    __table_args__ = {"schema": "fin_users"}

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200))
    email: Mapped[str | None] = mapped_column(String(320), unique=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    password_hash: Mapped[str | None] = mapped_column(String(256))
    avatar_url: Mapped[str | None] = mapped_column(Text)
    oauth_provider: Mapped[str | None] = mapped_column(String(50))
    oauth_subject: Mapped[str | None] = mapped_column(String(256))
    oauth_access_token: Mapped[str | None] = mapped_column(Text)
    oauth_refresh_token: Mapped[str | None] = mapped_column(Text)
    oauth_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False, default="guest")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


class UserQuery(Base):
    """ORM model for ``fin_agents.user_queries``.

    Tracks every query submission through its full lifecycle.
    """

    __tablename__ = "user_queries"
    __table_args__ = {"schema": "fin_agents"}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    user_id: Mapped[str | None] = mapped_column(Text)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        query_status_sa_type, nullable=False, default="connecting"
    )
    is_ack: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    extra: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=datetime.utcnow
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)


__all__ = ["GuestUser", "UserQuery"]
