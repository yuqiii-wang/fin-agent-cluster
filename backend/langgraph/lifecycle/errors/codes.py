"""Error codes for the lifecycle package."""

# Thread not found in the registry or DB.
LIFECYCLE_THREAD_NOT_FOUND = "LC001"
# Node not found.
LIFECYCLE_NODE_NOT_FOUND = "LC002"
# Task not found.
LIFECYCLE_TASK_NOT_FOUND = "LC003"
# Attempted state transition on an already-terminal entity.
LIFECYCLE_ALREADY_TERMINAL = "LC004"
# Cancellation cascade failed unexpectedly.
LIFECYCLE_CANCEL_FAILED = "LC005"
# DB write error in lifecycle path.
LIFECYCLE_DB_ERROR = "LC006"
# SSE publish failed in lifecycle path (non-fatal).
LIFECYCLE_SSE_ERROR = "LC007"
# No checkpoint found for the requested re-explore fork.
LIFECYCLE_CHECKPOINT_NOT_FOUND = "LC008"
# Re-explore graph invocation failed unexpectedly.
LIFECYCLE_REEXPLORE_FAILED = "LC009"

__all__ = [
    "LIFECYCLE_THREAD_NOT_FOUND",
    "LIFECYCLE_NODE_NOT_FOUND",
    "LIFECYCLE_TASK_NOT_FOUND",
    "LIFECYCLE_ALREADY_TERMINAL",
    "LIFECYCLE_CANCEL_FAILED",
    "LIFECYCLE_DB_ERROR",
    "LIFECYCLE_SSE_ERROR",
    "LIFECYCLE_CHECKPOINT_NOT_FOUND",
    "LIFECYCLE_REEXPLORE_FAILED",
]
