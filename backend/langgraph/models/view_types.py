"""View-type constants matching the PostgreSQL ENUM definitions in fin_agents.sql.

DB ENUMs
--------
``fin_agents.task_view_types``  -- used in ``fin_agents.tasks.view_type``
``fin_agents.node_view_types``  -- used in ``fin_agents.nodes.view_type``
"""

from __future__ import annotations

from typing import Literal

# ---------------------------------------------------------------------------
# task_view_types  (fin_agents.task_view_types ENUM)
# ---------------------------------------------------------------------------

TaskViewType = Literal["Streaming", "WebRequest", "Stats", "ToolCall", "Markdown", "Json"]

TASK_VIEW_STREAMING: TaskViewType = "Streaming"
TASK_VIEW_WEB_REQUEST: TaskViewType = "WebRequest"
TASK_VIEW_STATS: TaskViewType = "Stats"
TASK_VIEW_TOOL_CALL: TaskViewType = "ToolCall"
TASK_VIEW_MARKDOWN: TaskViewType = "Markdown"
TASK_VIEW_JSON: TaskViewType = "Json"

# ---------------------------------------------------------------------------
# node_view_types  (fin_agents.node_view_types ENUM)
# ---------------------------------------------------------------------------

NodeViewType = Literal["Stats", "Markdown", "Json", "Mirror", "Hybrid"]

NODE_VIEW_STATS: NodeViewType = "Stats"
NODE_VIEW_MARKDOWN: NodeViewType = "Markdown"
NODE_VIEW_JSON: NodeViewType = "Json"
NODE_VIEW_MIRROR: NodeViewType = "Mirror"
NODE_VIEW_HYBRID: NodeViewType = "Hybrid"

__all__ = [
    "TaskViewType",
    "TASK_VIEW_STREAMING",
    "TASK_VIEW_WEB_REQUEST",
    "TASK_VIEW_STATS",
    "TASK_VIEW_TOOL_CALL",
    "TASK_VIEW_MARKDOWN",
    "TASK_VIEW_JSON",
    "NodeViewType",
    "NODE_VIEW_STATS",
    "NODE_VIEW_MARKDOWN",
    "NODE_VIEW_JSON",
    "NODE_VIEW_MIRROR",
    "NODE_VIEW_HYBRID",
]
