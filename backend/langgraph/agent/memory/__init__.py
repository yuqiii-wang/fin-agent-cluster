"""backend.langgraph.agent.memory — unified node-scoped memory for agents.

Two entry flavours exist per node:

* **Task-backed memory** — entry references a ``fin_agents.tasks`` row;
  content is derived from the task's latest ``fin_agents.task_executions``
  output when read.
* **Direct memory** — arbitrary JSON payload stored directly in the memory
  row; must be non-empty.

All entries are scoped to a single ``node_id``.
"""

from __future__ import annotations

from backend.langgraph.agent.memory.models import (
    MemoryCheckItem,
    MemoryItem,
)
from backend.langgraph.agent.memory.ops import (
    check_memory,
    delete_memory,
    get_memory_by_id,
    get_memory_by_name,
    list_memory,
    write_memory,
)

__all__ = [
    "MemoryCheckItem",
    "MemoryItem",
    "check_memory",
    "delete_memory",
    "get_memory_by_id",
    "get_memory_by_name",
    "list_memory",
    "write_memory",
]
