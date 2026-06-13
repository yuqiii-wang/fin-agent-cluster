"""global_state.py -- Cross-iteration agent state for prepare_derivatives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.langgraph.models.node_utils.agent_step_mixin import AgentGlobalStateBase

if TYPE_CHECKING:
    from backend.langgraph.models.common_tasks.task_seqs.navigate_web.load_markdown_from_url.models import (
        LoadMdFromUrlOutput,
    )


@dataclass
class DerivativesGlobalState(AgentGlobalStateBase):
    """Mutable cross-iteration state for the prepare_derivatives agent loop.

    Attributes:
        symbol:         Uppercased equity symbol being processed.
        md_pages:       Markdown pages loaded by ``step_load_markdown``; the
                        ``step_study_web`` step studies each to extract options.
        json_input:     Structured options JSON extracted by ``step_study_web``;
                        ``None`` until extraction succeeds.
        load_md_output: First successful loaded Markdown page, used as a
                        markdown fallback when sandbox extraction fails.
    """

    symbol: str = ""
    md_pages: "list[LoadMdFromUrlOutput]" = field(default_factory=list, repr=False)
    json_input: dict[str, Any] | None = None
    load_md_output: "LoadMdFromUrlOutput | None" = field(default=None, repr=False)


__all__ = ["DerivativesGlobalState"]
