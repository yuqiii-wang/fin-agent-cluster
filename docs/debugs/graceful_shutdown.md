# Debug: LangGraph Graceful Shutdown Integration

## Context

This document describes the integration of graceful shutdown for LangGraph durable execution, following the official [LangGraph documentation](https://docs.langchain.com/oss/python/langgraph/durable-execution#graceful-shutdown).

## Approach

- On SIGINT/SIGTERM, the FastAPI app triggers a graceful shutdown.
- All running LangGraph queries are checkpointed and paused using the durable execution API.
- New queries are rejected with a shutdown-in-progress error.
- The process exits only after all running flows are safely checkpointed.

## Implementation Steps

1. Add a shutdown handler in `backend/main.py` using FastAPI lifespan context.
2. On shutdown, iterate over all running tasks in `backend.api.registry.running_tasks`.
3. For each running LangGraph task, trigger a checkpoint/pause (using the LangGraph RunControl API if available, or by cancelling the task to force checkpoint).
4. Log and emit error codes from `backend/graph/errors/SHUTDOWN.md` if any issues occur.
5. Ensure the process exits only after all tasks are safely paused.

## Notes
- This approach avoids hardcoded time lags and ensures all flows are safely checkpointed.
- Error codes are used for observability and debugging.

---

_Last updated: 2026-05-07_
