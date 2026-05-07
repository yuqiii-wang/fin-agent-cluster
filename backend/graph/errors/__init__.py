"""Graph runner error code registry package.

Re-exports all error code constants and the ``GRAPH_RUNNER_ERRORS`` description dict::

    from backend.graph.errors import GRAPH_RUNNER_ERRORS, GRAPH_NOT_INITIALIZED
"""

from __future__ import annotations

from backend.graph.errors.codes import (
    GRAPH_RUNNER_ERRORS,
    GRAPH_NOT_INITIALIZED,
    GRAPH_DB_UNAVAILABLE,
)

__all__ = [
    "GRAPH_RUNNER_ERRORS",
    "GRAPH_NOT_INITIALIZED",
    "GRAPH_DB_UNAVAILABLE",
     "SHUTDOWN.md",
]
