# Debug: query_node slow (32–64s) while analyze_query task shows fast

## Symptom

- Frontend task Gantt shows `analyze_query` task completing quickly (~150ms SSE ack)
- But the `query_node` bar stays "running" for 32–64 seconds before `research_subgraph` starts
- Log: `[lifecycle:task] running SSE done task_id=3751166a sse_ms=99` then **64-second silence** before
  `[lifecycle:node] running research_subgraph`

## Root Cause

**The Celery worker was not running** (or had just restarted) when the `analyze_query` task was
dispatched to the queue.  The task sat in the Celery/Redis broker queue with no worker to consume it.
After ~64 s the worker eventually started and picked it up.

### Evidence

From `centrifugo.log` for thread `f15adf71`:
```
14:23:37.267  [sse:task] ack received  task:3751166a:running    attempt_ms=72
14:24:41.339  [rpc_proxy] ack          task:3751166a:completed  (64 seconds later!)
14:24:41.430  [rpc_proxy] ack          node:research_subgraph:running
```

From `graph.log`: the `[analyze_query] query='semantic test'` INFO log (emitted by the Celery handler
**inside** the worker) is **absent** for this thread — the worker never logged it at dispatch time.
All fast runs (~63 ms) have this log within 50 ms of task dispatch.

### Why `complete_node` for query_node had no log

`complete_node(success)` was called after `delegate_completion` returned, but found the node already
in a terminal state (`updated=0`, silent early-return). This occurs when:

1. The graph runner restarts → `recover_pending_runs` picks up the thread (status='running' in DB)
   and calls `graph.ainvoke(None, resume=True)`.
2. The LangGraph checkpoint was before query_node completed → LangGraph re-runs query_node.
3. If a **previous** run (before restart) had already set `fin_agents.nodes.query_node` to a
   terminal status, the new `complete_node(success)` call finds 0 rows to update and returns
   silently.

## Timeline of Graph Runner Restart

```
14:23:05   graph compiled (old consumers starting)
14:23:23   [graph_runner] shutdown requested consumer=yuqiwinpc-3879-1 / 3878-0
14:23:23   consumers exited cleanly (43 ms — no in-flight tasks)
14:23:29   graph compiled (new consumers starting)
14:23:36   query_node running for f15adf71 (new consumer processing)
14:23:37   task dispatched to Celery, running SSE acked (99 ms)
           → Celery worker NOT running at this moment
14:24:41   Celery worker picks up task, processes in ~150 ms, returns result
           → delegate_completion unblocks after 64 s total
14:24:41   research_subgraph starts immediately (complete_node silent no-op)
```

## Diagnostic Logs Added

### `backend/celery_task/workers/task_delegation.py`

- **`delegate_completion`**: logs `[task_delegation] celery done task_id=... celery_ms=...` after
  Celery returns. If `celery_ms > 5000`, logs at ERROR level as
  `[task_delegation] slow celery task_id=... celery_ms=...`.
- **`_await_result`**: logs ERROR every 30 s while waiting:
  `[task_delegation] waiting for celery task_id=... elapsed_s=...`.

### `backend/celery_task/workers/tasks/completion_task.py`

- Logs `[completion_task] start task_id=... task_name=... thread_id=...` when the worker
  **actually begins** processing (confirms worker is alive and picked it up).
- Logs `[completion_task] done task_id=... handler_ms=...` after the handler + DB write completes.

### `backend/langgraph/lifecycle/threads/nodes/__init__.py`

- When `complete_node` would silently skip due to `updated=0`, now logs ERROR:
  `[lifecycle:node] completed skipped node_id=... existing_status=... — node already terminal`
  with a DB lookup showing the current status.

### `backend/langgraph/lifecycle/threads/nodes/tasks/__init__.py`

- When `complete_task` silently skips due to `updated=0`, now logs ERROR:
  `[lifecycle:task] completed skipped task_id=... — task already terminal`

## How to Reproduce / Verify Fix

1. Ensure Celery worker is running **before** starting the graph runner.
2. Run a query immediately after a graph runner restart — watch `graph.log` for
   `[task_delegation] slow celery` (> 5 s) or `[task_delegation] waiting for celery` (30 s boundary).
3. Check `streaming.log` for `[completion_task] start` — its timestamp relative to
   `[lifecycle:task] created` in `graph.log` shows the queue wait time directly.

## Mitigation

- Start Celery workers before the FastAPI/graph-runner process in `run.py` / `setup.sh`.
- Monitor `[task_delegation] slow celery` alerts (now ERROR-level) to detect worker absence early.
- The `_COMPLETION_TIMEOUT = 120 s` in `task_delegation.py` will eventually surface a
  `TimeoutError` and fail the task cleanly if the worker never comes up.
