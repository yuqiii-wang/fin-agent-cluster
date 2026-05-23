"""Error codes for the backend.langgraph.agent module."""

# Pause flag was already set when the API tried to set it again.
AGENT_PAUSE_ALREADY_SET = "AG001"
# No saved agent state found when trying to resume.
AGENT_STATE_NOT_FOUND = "AG002"
# Memory entry not found or not owned by the given node.
AGENT_MEMORY_NOT_FOUND = "AG003"
# Skill not found or not owned by the given node.
AGENT_SKILL_NOT_FOUND = "AG004"
# Agent node is not currently running; pause-triggering operation skipped.
AGENT_NOT_RUNNING = "AG005"
# compact_memory_entries requires at least 2 active entries.
AGENT_COMPACT_TOO_FEW_ENTRIES = "AG006"
# Agent loop hit max_iterations without reaching a final answer.
AGENT_MAX_ITERATIONS = "AG007"

__all__ = [
    "AGENT_COMPACT_TOO_FEW_ENTRIES",
    "AGENT_MAX_ITERATIONS",
    "AGENT_MEMORY_NOT_FOUND",
    "AGENT_NOT_RUNNING",
    "AGENT_PAUSE_ALREADY_SET",
    "AGENT_SKILL_NOT_FOUND",
    "AGENT_STATE_NOT_FOUND",
]
