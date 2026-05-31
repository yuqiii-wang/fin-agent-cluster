"""Error codes for agent API endpoints."""

# The node_id was not found in the DB for the given thread.
AGENT_API_NODE_NOT_FOUND = "AGAPI001"
# The requested node is not of type AGENT; operation not applicable.
AGENT_API_NOT_AGENT_TYPE = "AGAPI002"
# The requested skill was not found or does not belong to this node.
AGENT_API_SKILL_NOT_FOUND = "AGAPI004"

__all__ = [
    "AGENT_API_NODE_NOT_FOUND",
    "AGENT_API_NOT_AGENT_TYPE",
    "AGENT_API_SKILL_NOT_FOUND",
]
