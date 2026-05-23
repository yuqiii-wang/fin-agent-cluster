"""backend.langgraph.agent.tools — NodeTask-to-StructuredTool bridge layer.

NodeTask is the canonical task definition; this package exposes the lightweight
ToolInfo metadata model and helpers that convert NodeTask registries into the
representation used by capability selection and the agent loop.
"""

from __future__ import annotations

from backend.langgraph.agent.tools.models import ToolInfo
from backend.langgraph.agent.tools.ops import get_tool_infos_for_tasks, get_tools_for_node

__all__ = [
    "ToolInfo",
    "get_tool_infos_for_tasks",
    "get_tools_for_node",
]
