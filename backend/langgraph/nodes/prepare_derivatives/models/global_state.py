"""global_state.py — Cross-iteration agent state for prepare_derivatives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.langgraph.models.node_utils.agent_step_mixin import AgentGlobalStateBase

if TYPE_CHECKING:
    from backend.langgraph.models.common_tasks.task_seqs.navigate_web.models import (
        NavigateWebPerUrlOutput,
    )


@dataclass
class DerivativesGlobalState(AgentGlobalStateBase):
    """Mutable state carried across prepare_derivatives agent steps.

    Extends :class:`~backend.langgraph.models.node_utils.agent_step_mixin.AgentGlobalStateBase`
    with prepare_derivatives-specific fields.

    Attributes:
        symbol:         Uppercased equity ticker resolved from query_node.
        json_input:     Merged structured options JSON parsed from the sandbox
                        outputs of ``step_navigate_web``; ``None`` when the step
                        was skipped or all URL pipelines failed.
        load_md_output: First successful per-URL pipeline output from
                        ``step_navigate_web``; used by ``step_get_stats`` as a
                        fallback source of Markdown text when sandbox extraction
                        produced no valid JSON.
    """

    symbol: str = ""
    json_input: dict[str, Any] | None = None
    load_md_output: "NavigateWebPerUrlOutput | None" = field(default=None, repr=False)


__all__ = ["DerivativesGlobalState"]

