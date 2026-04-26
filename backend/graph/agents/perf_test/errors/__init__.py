"""Perf-test agent error code registry package.

Re-exports all error code constants and the ``PT_AGENT_ERRORS`` description dict::

    from backend.graph.agents.perf_test.errors import (
        PT_AGENT_ERRORS,
        PT_STOP_REQUESTED,
    )
"""

from __future__ import annotations

from backend.graph.agents.perf_test.errors.codes import (
    PT_AGENT_ERRORS,
    PT_STOP_REQUESTED,
)

__all__ = [
    "PT_AGENT_ERRORS",
    "PT_STOP_REQUESTED",
]
