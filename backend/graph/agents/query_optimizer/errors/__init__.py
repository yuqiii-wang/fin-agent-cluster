"""Query-optimizer agent error code registry package.

Re-exports all error code constants and the ``QO_AGENT_ERRORS`` description dict::

    from backend.graph.agents.query_optimizer.errors import (
        QO_AGENT_ERRORS,
        QO_COMPREHEND_FAILED,
        QO_VALIDATE_FAILED,
        QO_POPULATE_FAILED,
        QO_SEC_PROFILE_FAILED,
    )
"""

from __future__ import annotations

from backend.graph.agents.query_optimizer.errors.codes import (
    QO_AGENT_ERRORS,
    QO_COMPREHEND_FAILED,
    QO_VALIDATE_FAILED,
    QO_POPULATE_FAILED,
    QO_SEC_PROFILE_FAILED,
)

__all__ = [
    "QO_AGENT_ERRORS",
    "QO_COMPREHEND_FAILED",
    "QO_VALIDATE_FAILED",
    "QO_POPULATE_FAILED",
    "QO_SEC_PROFILE_FAILED",
]
