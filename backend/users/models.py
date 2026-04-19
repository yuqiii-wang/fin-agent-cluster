"""ORM models for user management and submitted queries."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, Boolean, CheckConstraint, Index, String, Text, func, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.db.postgres.base import Base


class GuestUser(Base):
    """User row — supports guest, password, and OAuth authentication modes.

    Columns are additive so a guest account can be progressively upgraded to
    a full password or OAuth account without re-creating the row.
    """

    __tablename__ = "users"
    __table_args__ = (
        Index("fin_users_users_email_idx", "email"),
        Index("fin_users_users_oauth_idx", "oauth_provider", "oauth_subject"),
        {"schema": "fin_users"},
    )

    # Primary key — UUID bearer token for guests, surrogate PK for password/OAuth users
    id: Mapped[str] = mapped_column(String(36), primary_key=True)

    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True, unique=True)
    email_verified: Mapped[bool] = mapped_column(nullable=False, default=False)
    password_hash: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # OAuth — all nullable until provider links the account
    oauth_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    oauth_subject: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    oauth_access_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    oauth_refresh_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    oauth_token_expires_at: Mapped[Optional[datetime]] = mapped_column(TIMESTAMP, nullable=True)

    # Auth mode: 'guest' | 'password' | 'oauth'
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False, default="guest")
    is_active: Mapped[bool] = mapped_column(nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=func.now()
    )


class UserQuery(Base):
    """One row per user request; thread_id is the LangGraph correlation key."""

    __tablename__ = "user_queries"

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed', 'cancelled')",
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
