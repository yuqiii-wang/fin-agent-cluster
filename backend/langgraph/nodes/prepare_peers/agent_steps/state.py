"""state.py — Shared state models for the prepare_peers agent step loop.

Models
------
``StepResult``         — Per-step execution record passed to LLM orchestration.
``AgentGlobalState``   — Cross-iteration mutable state (extends ``AgentGlobalStateBase``).
``IterationStepState`` — Per-iteration mutable state, reset each outer loop turn.
``StepRunContext``     — Context bundle injected into every step function.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from pydantic import BaseModel, Field

from backend.langgraph.models.models import NodeContext, TaskOutput
from backend.langgraph.nodes.prepare_peers.models.global_state import AgentGlobalState

if TYPE_CHECKING:
    from backend.langgraph.nodes.prepare_peers.tasks.analyze_peer_corr import (
        AnalyzePeerCorrOutput,
        PeerRawCorrData,
    )


__all__ = [
    "StepResult",
    "AgentGlobalState",
    "IterationStepState",
    "StepRunContext",
]


class StepResult(BaseModel):
    """Execution record for a single step, surfaced to the LLM orchestration task.

    Attributes:
        step:           Step name from ``STEP_ORDER``.
        success:        ``True`` when the step completed without raising.
        output_summary: Lightweight serialisable dict for LLM consumption.
                        Must not include heavy data blobs (DataFrames, matrices).
        failure_reason: Exception message when ``success=False``.
    """

    step: str
    success: bool
    output_summary: dict[str, Any] = Field(default_factory=dict)
    failure_reason: str | None = None


@dataclass
class IterationStepState:
    """Mutable state scoped to a single outer-loop iteration.

    Attributes:
        iteration:       Outer iteration counter (1-based).
        proposed_url:    URL produced by ``propose_url`` or injected via override.
        new_peers:       Peer tickers parsed from sandbox JSON by ``navigate_web``.
        valid_peers:     Peers that survived ``fetch_stats`` + ``filter_co_index``.
        iter_peer_raw:   Raw ``calculate_corr`` output keyed by peer symbol.
        apc_output:      Populated by ``step_analyze_corr``; used in ``_post_iteration_hook``.
        step_results:    Per-step execution records for LLM orchestration context.
        input_overrides: LLM-supplied input overrides for individual step functions.
    """

    iteration: int
    proposed_url: str = ""
    new_peers: list[str] = field(default_factory=list)
    valid_peers: list[str] = field(default_factory=list)
    iter_peer_raw: dict[str, PeerRawCorrData] = field(default_factory=dict)
    apc_output: AnalyzePeerCorrOutput | None = None
    step_results: dict[str, StepResult] = field(default_factory=dict)
    input_overrides: dict[str, Any] = field(default_factory=dict)


@dataclass
class StepRunContext:
    """Context bundle passed to every step function.

    Attributes:
        run_task:                  Bound ``BaseNode.run_task`` callable.
        ctx:                       Current ``NodeContext``.
        g:                         Cross-iteration global state.
        s:                         Current iteration step state.
        results:                   Accumulated ``TaskOutput`` dict for the agent runner.
        stock_name:                Original stock name from node input.
        peers_output_schema:       JSON schema injected into ``navigate_web``.
        peer_discovery_objective:  Objective template string for ``navigate_web``.
        peers_extraction_skill:    Markdown skill text injected into ``navigate_web``.
    """

    run_task: Callable[..., Awaitable[Any]]
    ctx: NodeContext
    g: AgentGlobalState
    s: IterationStepState
    results: dict[str, TaskOutput]
    stock_name: str
    peers_output_schema: dict
    peer_discovery_objective: str
    peers_extraction_skill: str



