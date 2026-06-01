"""Error codes for the backend.langgraph.agent.error_log module."""

# Redis write of a per-thread log entry failed in the background writer.
ERRLOG_WRITE_FAILED = "EL001"
# Redis read of a thread's error-log store failed during orchestration.
ERRLOG_READ_FAILED = "EL002"

__all__ = [
    "ERRLOG_WRITE_FAILED",
    "ERRLOG_READ_FAILED",
]
