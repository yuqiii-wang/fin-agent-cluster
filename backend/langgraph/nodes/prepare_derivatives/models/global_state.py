"""global_state.py — Cross-iteration agent state for prepare_derivatives."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.langgraph.models.node_utils.agent_step_mixin import AgentGlobalStateBase


@dataclass
class DerivativesGlobalState(AgentGlobalStateBase):
    """Mutable state carried across prepare_derivatives agent steps.

    Extends :class:`~backend.langgraph.models.node_utils.agent_step_mixin.AgentGlobalStateBase`
    with prepare_derivatives-specific fields.

    Attributes:
        symbol:             Uppercased equity ticker resolved from query_node.
        web_knowledge_url:  URL returned by ``propose_web_knowledge_urls``.
        json_input:         Structured JSON parsed from the sandbox stdout of
                            ``navigate_web``; ``None`` when the step was skipped
                            or failed (``get_and_calculate_stats`` accepts ``None``).
    """

    symbol: str = ""
    web_knowledge_url: str = ""
    json_input: dict[str, Any] | None = None


__all__ = ["DerivativesGlobalState"]
