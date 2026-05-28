"""agent_steps — prepare_peers per-step implementation package.

Exports
-------
- ``AGENT_STEPS``          — Dict mapping step name → step coroutine function.
- ``STEP_ORDER``           — Canonical step execution order.
- Step name constants      — ``STEP_PROPOSE_URL``, ``STEP_NAVIGATE_WEB``, etc.
- ``AgentGlobalState``     — Cross-iteration mutable state (lives in models/).
- ``IterationStepState``   — Per-iteration mutable state dataclass.
- ``StepRunContext``       — Context bundle injected into every step function.
- ``StepResult``           — Per-step execution record (Pydantic model).
"""

from backend.langgraph.nodes.prepare_peers.agent_steps.constants import (
    STEP_ANALYZE_CORR,
    STEP_CALCULATE_CORR,
    STEP_FETCH_STATS,
    STEP_FILTER_CO_INDEX,
    STEP_NAVIGATE_WEB,
    STEP_ORDER,
    STEP_PROPOSE_URL,
    _CORR_THRESHOLD,
    _CORR_WINDOW_BARS,
    _VALIDATION_GRANULARITY,
    _VALIDATION_PERIOD,
)
from backend.langgraph.nodes.prepare_peers.agent_steps.registry import AGENT_STEPS
from backend.langgraph.nodes.prepare_peers.agent_steps.state import (
    IterationStepState,
    StepResult,
    StepRunContext,
)
from backend.langgraph.nodes.prepare_peers.models.global_state import AgentGlobalState

__all__ = [
    # Registry
    "AGENT_STEPS",
    # Constants
    "STEP_ORDER",
    "STEP_PROPOSE_URL",
    "STEP_NAVIGATE_WEB",
    "STEP_FETCH_STATS",
    "STEP_FILTER_CO_INDEX",
    "STEP_CALCULATE_CORR",
    "STEP_ANALYZE_CORR",
    # Private numeric constants (re-exported for node.py usage)
    "_VALIDATION_PERIOD",
    "_VALIDATION_GRANULARITY",
    "_CORR_WINDOW_BARS",
    "_CORR_THRESHOLD",
    # State models
    "AgentGlobalState",
    "IterationStepState",
    "StepRunContext",
    "StepResult",
]
