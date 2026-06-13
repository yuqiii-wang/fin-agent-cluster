"""state.py -- Step context for prepare_derivatives agent steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from backend.langgraph.models.models import NodeContext, TaskOutput
from backend.langgraph.nodes.prepare_derivatives.models.global_state import (
    DerivativesGlobalState,
)


@dataclass
class DerivativesStepContext:
    """Bundle injected into every prepare_derivatives step function.

    Attributes:
        run_task:        Bound ``BaseNode.run_task`` used by steps to run NodeTasks.
        ctx:             Current node context.
        g:               Cross-iteration global state.
        results:         Accumulated keyed ``TaskOutput`` dict (mutable).
        stats_period:    Lookback period for OHLCV stats calculation.
        failure_context: Guidance string (prior failure reason + orchestration
                         reasoning) forwarded to the regenerated streaming step
                         on a retry iteration; empty on the first iteration.
    """

    run_task: Callable[..., Awaitable[Any]]
    ctx: NodeContext
    g: DerivativesGlobalState
    results: dict[str, TaskOutput]
    stats_period: str
    failure_context: str = ""


__all__ = ["DerivativesStepContext"]
