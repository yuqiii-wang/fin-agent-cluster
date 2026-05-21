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
    "WorkStatus",
    "work_status_sa_type",
    "NodeType",
    "node_type_sa_type",
]


class QueryStatus(StrEnum):
    """Valid values for ``fin_agents.query_status`` Postgres enum.

    Using ``StrEnum`` means instances compare equal to plain strings, so
    existing code that checks ``status == "running"`` continues to work.
    """

    CONNECTING = "connecting"
    RECEIVED = "received"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


# SQLAlchemy column type that maps to the *existing* Postgres enum.
# ``create_type=False`` prevents SQLAlchemy from issuing CREATE TYPE on
# metadata creation; the type is already defined in fin_agents.sql.
query_status_sa_type = SAEnum(
    *[s.value for s in QueryStatus],
    name="query_status",
    schema="fin_agents",
    create_type=False,
)


class WorkStatus(StrEnum):
    """Valid values for ``fin_agents.work_status`` Postgres enum.

    Applies to both ``fin_agents.nodes.status`` and ``fin_agents.tasks.status``.
    Using ``StrEnum`` means instances compare equal to plain strings, so
    existing code that checks ``status == "running"`` continues to work.
    """

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WRONG = "wrong"


work_status_sa_type = SAEnum(
    *[s.value for s in WorkStatus],
    name="work_status",
    schema="fin_agents",
    create_type=False,
)


class NodeType(StrEnum):
    """Valid values for ``fin_agents.node_types`` Postgres enum.

    Applies to ``fin_agents.nodes.type``.
    Using ``StrEnum`` means instances compare equal to plain strings.
    """

    WORKFLOW = "Workflow"
    SUBGRAPH = "Subgraph"


node_type_sa_type = SAEnum(
    *[s.value for s in NodeType],
    name="node_types",
    schema="fin_agents",
    create_type=False,
)

