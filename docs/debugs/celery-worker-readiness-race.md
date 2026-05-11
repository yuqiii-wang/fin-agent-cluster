# Debug: analyze_query slow (64s) + node already terminal after recovery

## Symptoms

Two errors appear together in the logs:

```
23:30:57 | ERROR | Stream/Workers | [task_delegation] waiting for celery task_id=ab28bfbb elapsed_s=30 celery_state=STARTED
23:31:27 | ERROR | Stream/Workers | [task_delegation] waiting for celery task_id=ab28bfbb elapsed_s=60 celery_state=STARTED
23:31:31 | ERROR | Stream/Workers | [task_delegation] slow celery task_id=ab28bfbb task_name=analyze_query celery_ms=64133
23:31:31 | ERROR | Graph/Lifecycle | [lifecycle:node] completed skipped node_id=...:query_node existing_status=completed — node already terminal
```

## Root Cause

### Error 1 — 64-second Celery queue lag

`run.py` started the Celery worker cluster (`_start_celery_cluster`) and
then **immediately** started the graph runners (`_start_graph_runners`) with
no readiness gate.  The graph runner processed a queued run before the Celery
workers had finished connecting to the Redis broker and registering as
consumers.  The `analyze_query` task was pushed to the broker queue but sat
unprocessed for ~64 s until a worker became available.

`celery_state=STARTED` (rather than `PENDING`) in the 30 s / 60 s warning
logs confirms the worker eventually picked it up and ran it — the delay is
pure queue-wait time, not slow handler execution.

### Error 2 — node already terminal

This is a **downstream consequence** of Error 1 combined with the
`recover_pending_runs` crash-recovery mechanism:

1. The graph runner restarts while the `analyze_query` Celery task is still
   sitting in the broker queue.
2. `recover_pending_runs` picks up the thread (status=`running` in DB) and
   re-runs it from the last LangGraph checkpoint.
3. The recovery run executes `query_node` again, dispatches a NEW Celery
   task (which now completes quickly), and calls `complete_node` — marking
   the node row as `completed` in `fin_agents.nodes`.
4. Meanwhile, the OLD Celery task from step 1 finally completes (64 s later)
   and the original `delegate_completion` returns.  The original
   `query_node` call then tries `complete_node`, which finds `updated=0`
   (node already terminal) and logs the ERROR.

The graph continues executing correctly — LangGraph uses its own checkpoint
system and does not depend on the `fin_agents.nodes` status.

## Fix

`_wait_for_ondemand_workers()` was added to `run.py`.  It polls
`celery_engine.control.inspect(timeout=3).ping()` in a retry loop (up to
20 attempts, 2 s between tries) after `_start_celery_cluster` returns.
`_start_graph_runners` is only called once at least one worker responds.

```
run.py startup order (after fix):
  1. _start_celery_cluster()
  2. _wait_for_ondemand_workers()   ← NEW: blocks until workers are ready
  3. _start_graph_runners()
  4. _start_uvicorn_instances()
```

If no workers respond within `max_retries` attempts, a WARNING is printed
and startup continues (non-fatal) so the system still runs in degraded mode.

## Files Changed

- `run.py`: added `_wait_for_ondemand_workers()` function; called it after
  `_start_celery_cluster()` and before `_start_graph_runners()`.
