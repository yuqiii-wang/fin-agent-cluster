"""Error codes for the backend.langgraph.agent module."""

# Pause flag was already set when the API tried to set it again.
AGENT_PAUSE_ALREADY_SET = "AG001"
# No saved agent state found when trying to resume.
AGENT_STATE_NOT_FOUND = "AG002"
# Skill not found or not owned by the given node.
AGENT_SKILL_NOT_FOUND = "AG004"
# Agent node is not currently running; pause-triggering operation skipped.
AGENT_NOT_RUNNING = "AG005"

__all__ = [
    "AGENT_NOT_RUNNING",
    "AGENT_PAUSE_ALREADY_SET",
    "AGENT_SKILL_NOT_FOUND",
    "AGENT_STATE_NOT_FOUND",
]
