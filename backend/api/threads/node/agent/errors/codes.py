"""Error codes for agent API endpoints."""

# The node_id was not found in the DB for the given thread.
AGENT_API_NODE_NOT_FOUND = "AGAPI001"
# The requested node is not of type AGENT; operation not applicable.
AGENT_API_NOT_AGENT_TYPE = "AGAPI002"
# The requested memory entry was not found or does not belong to this node.
AGENT_API_MEMORY_NOT_FOUND = "AGAPI003"
# The requested skill was not found or does not belong to this node.
AGENT_API_SKILL_NOT_FOUND = "AGAPI004"
# compact_memory requires at least 2 active memory entries.
AGENT_API_COMPACT_TOO_FEW = "AGAPI005"
# No step-state rows found for the requested node.
AGENT_API_STEP_STATE_NOT_FOUND = "AGAPI006"

__all__ = [
    "AGENT_API_COMPACT_TOO_FEW",
    "AGENT_API_MEMORY_NOT_FOUND",
    "AGENT_API_NODE_NOT_FOUND",
    "AGENT_API_NOT_AGENT_TYPE",
    "AGENT_API_SKILL_NOT_FOUND",
    "AGENT_API_STEP_STATE_NOT_FOUND",
]
