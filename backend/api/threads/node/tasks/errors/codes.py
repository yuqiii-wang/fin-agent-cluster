"""Error codes for task-level API operations."""

# The requested task or thread was not found in the DB.
TASK_RETRY_NOT_FOUND = "TR001"
# The task is still running or is in a state that cannot be retried
# (e.g. 'wrong' status set by zombie cleanup).
TASK_RETRY_NOT_RETRYABLE = "TR002"
# The Celery dispatch or background execution of the retry failed unexpectedly.
TASK_RETRY_DISPATCH_FAILED = "TR003"
# compact_and_continue requested but no prior llm_responses row exists for this task.
TASK_RETRY_NO_PRIOR_LLM_RESPONSE = "TR004"
# continue requested but the task is not in 'paused' state.
TASK_CONTINUE_NOT_PAUSED = "TR005"

__all__ = [
    "TASK_RETRY_NOT_FOUND",
    "TASK_RETRY_NOT_RETRYABLE",
    "TASK_RETRY_DISPATCH_FAILED",
    "TASK_RETRY_NO_PRIOR_LLM_RESPONSE",
    "TASK_CONTINUE_NOT_PAUSED",
]
