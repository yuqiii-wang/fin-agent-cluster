"""registry.py — Assembles the AGENT_STEPS dict for the prepare_peers node."""

from __future__ import annotations

from typing import Awaitable, Callable

from backend.langgraph.nodes.prepare_peers.agent_steps.analyze_corr import step_analyze_corr
from backend.langgraph.nodes.prepare_peers.agent_steps.calculate_corr import step_calculate_corr
from backend.langgraph.nodes.prepare_peers.agent_steps.constants import (
    STEP_ANALYZE_CORR,
    STEP_CALCULATE_CORR,
    STEP_FETCH_STATS,
    STEP_FILTER_CO_INDEX,
    STEP_NAVIGATE_WEB,
    STEP_PROPOSE_URL,
)
from backend.langgraph.nodes.prepare_peers.agent_steps.fetch_stats import step_fetch_stats
from backend.langgraph.nodes.prepare_peers.agent_steps.filter_co_index import step_filter_co_index
from backend.langgraph.nodes.prepare_peers.agent_steps.navigate_web import step_navigate_web
from backend.langgraph.nodes.prepare_peers.agent_steps.propose_url import step_propose_url
from backend.langgraph.nodes.prepare_peers.agent_steps.state import StepRunContext

#: Mapping of step name → async step function.
#: Used by the generic ``AgentStepMixin._run_agent_step_loop``.
AGENT_STEPS: dict[str, Callable[[StepRunContext], Awaitable[None]]] = {
    STEP_PROPOSE_URL: step_propose_url,
    STEP_NAVIGATE_WEB: step_navigate_web,
    STEP_FETCH_STATS: step_fetch_stats,
    STEP_FILTER_CO_INDEX: step_filter_co_index,
    STEP_CALCULATE_CORR: step_calculate_corr,
    STEP_ANALYZE_CORR: step_analyze_corr,
}

__all__ = ["AGENT_STEPS"]
