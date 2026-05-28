"""registry.py — Assembles the AGENT_STEPS dict for prepare_derivatives."""

from __future__ import annotations

from typing import Awaitable, Callable

from backend.langgraph.nodes.prepare_derivatives.agent_steps.constants import (
    STEP_GET_STATS,
    STEP_NAVIGATE_WEB,
    STEP_PROPOSE_URL,
)
from backend.langgraph.nodes.prepare_derivatives.agent_steps.get_stats import step_get_stats
from backend.langgraph.nodes.prepare_derivatives.agent_steps.navigate_web import step_navigate_web
from backend.langgraph.nodes.prepare_derivatives.agent_steps.propose_url import step_propose_url
from backend.langgraph.nodes.prepare_derivatives.agent_steps.state import DerivativesStepContext

#: Mapping of step name → async step function.
AGENT_STEPS: dict[str, Callable[[DerivativesStepContext], Awaitable[None]]] = {
    STEP_PROPOSE_URL: step_propose_url,
    STEP_NAVIGATE_WEB: step_navigate_web,
    STEP_GET_STATS: step_get_stats,
}

__all__ = ["AGENT_STEPS"]
