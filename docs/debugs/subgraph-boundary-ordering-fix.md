# Subgraph Boundary Ordering Fix

**Thread investigated:** `d26a1be2-a875-4ff4-9dc3-9adb1620049d`

## Symptom

UI timeline showed `conclusion_node` starting (at ~11.579s) before `research_subgraph / merge_node` ended (displayed as ending at ~11.993s), giving a visual overlap that implied incorrect execution order.

## Root Cause 1 — `elapsed_ms` SQL Integer Truncation

### Location
- `backend/langgraph/lifecycle/threads/nodes/sql.py` → `_UPDATE_NODE_COMPLETED`
- `backend/db/postgres/queries/fin_agents.py` → `UPDATE_COMPLETED`

### The Bug

```sql
-- WRONG: casts seconds to INT first (nearest-second rounding), then multiplies
elapsed_ms = EXTRACT(EPOCH FROM (NOW() - started_at))::INT * 1000
```

PostgreSQL `EXTRACT(EPOCH ...)` returns a `float8`. Casting `::INT` rounds to
the nearest **second** before multiplying by 1000. A 542ms node becomes
`ROUND(0.542)::INT = 1` → `1 * 1000 = 1000ms` instead of 542ms.

### Evidence from DB (investigated thread)

```
merge_node: started_at=15:00:10.993304, updated_at=15:00:11.535316
Actual elapsed  = 542 ms
Stored elapsed_ms = 1000 ms   ← 1s rounding artefact
```

UI computed end time: `10.993 + 1.000 = 11.993s`
`conclusion_node` started at: `11.579s`
→ UI shows conclusion starting while merge still appears running (11.579 < 11.993).

DB timestamps confirm **execution order is correct** — merge truly completes
44ms before conclusion starts. The display was the only bug.

### Fix

```sql
-- CORRECT: multiply first (stay in float milliseconds), then round to nearest ms
elapsed_ms = ROUND(EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000)::INT
```

Accurate to ±0.5ms.

---

## Root Cause 2 — Task SSE Fired as Background `asyncio.create_task`

### Location
`backend/celery_task/workers/task_delegation.py` → `delegate_completion`

### The Bug

After receiving the Celery result, `delegate_completion` fired the
`task_status:completed` SSE as a **fire-and-forget** background task:

```python
asyncio.create_task(
    _emit_task_sse(..., status="completed", ...),
    name=f"sse-task-completed-{task_id}",
)
return result
```

The background coroutine runs **concurrently** with the main graph-runner flow
that calls `complete_node` next. Since all events for a thread share one
Centrifugo channel (`thread:{thread_id}`), the relative publish order is
non-deterministic.

Worst-case ordering on the channel:

```
1. merge_node:completed       ← main flow
2. research_subgraph:completed ← main flow
3. conclusion_node:running    ← main flow (LangGraph next step)
4. merge_results:task completed  ← LATE background task
```

The UI would show `merge_results` task still "running" after `conclusion_node`
started, and the task event would arrive out of order.

The same `asyncio.create_task` pattern existed for the `task:failed` path
(exception branch), with the same ordering risk.

### Fix

Both `asyncio.create_task` calls replaced with `await`:

```python
# Before returning — ensures task SSE is published + ACKed first
await _emit_task_sse(..., status="completed", ...)
return result
```

This guarantees the canonical order: `task:completed → node:completed →
subgraph:completed → next_node:running` on the shared channel.

---

## Affected Files

| File | Change |
|------|--------|
| `backend/langgraph/lifecycle/threads/nodes/sql.py` | `::INT * 1000` → `* 1000)::INT` with `ROUND(...)` |
| `backend/db/postgres/queries/fin_agents.py` | same |
| `backend/celery_task/workers/task_delegation.py` | `asyncio.create_task(_emit_task_sse(...))` → `await _emit_task_sse(...)` for both completed and failed paths |

---

## Why Execution Order Was Never Broken

The actual node lifecycle in `BaseNode.__call__` and `_run_as_child` correctly
`await`s `complete_node`, which in turn `await`s `emit_node_sse`, which `await`s
`notify` (ACK round-trip via Redis BLPOP). LangGraph does not proceed to the
next node until the current node's `__call__` returns. The DB timestamps
(`updated_at` / `started_at`) confirm this: there is always a positive gap
between one node's completion and the next node's start. Bug 1 was purely a
display artefact; Bug 2 was a potential (but rare in practice) ordering race.
