"""state.py — Step context for prepare_derivatives agent steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from backend.langgraph.models.models import NodeContext, TaskOutput
from backend.langgraph.nodes.prepare_derivatives.models.global_state import DerivativesGlobalState


@dataclass
class DerivativesStepContext:
    """Context bundle injected into every prepare_derivatives step function.

    Attributes:
        run_task:     Bound ``BaseNode.run_task`` callable.
        ctx:          Current ``NodeContext``.
        g:            Cross-iteration global state.
        results:      Accumulated ``TaskOutput`` dict (shared reference).
        stats_period: OHLCV aggregation period passed to ``get_and_calculate_stats``.
    """

    run_task: Callable[..., Awaitable[Any]]
    ctx: NodeContext
    g: DerivativesGlobalState
    results: dict[str, TaskOutput]
    stats_period: str


__all__ = ["DerivativesStepContext"]
