"""PostgreSQL custom types shared across ORM models.

Defines Python-level enum constants and their matching SQLAlchemy column types
so that native Postgres enum columns are reflected correctly and bind parameters
are never cast as ``::VARCHAR``.
"""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum as SAEnum

__all__ = [
    "QueryStatus",
    "query_status_sa_type",
]


class QueryStatus(StrEnum):
    """Valid values for ``fin_agents.query_status`` Postgres enum.

    Using ``StrEnum`` means instances compare equal to plain strings, so
    existing code that checks ``status == "running"`` continues to work.
    """

    RECEIVED = "received"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


# SQLAlchemy column type that maps to the *existing* Postgres enum.
# ``create_type=False`` prevents SQLAlchemy from issuing CREATE TYPE on
# metadata creation; the type is already defined in fin_agents.sql.
query_status_sa_type = SAEnum(
    *[s.value for s in QueryStatus],
    name="query_status",
    schema="fin_agents",
    create_type=False,
)

