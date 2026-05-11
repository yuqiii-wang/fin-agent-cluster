# Multi-FastAPI Graph Thread Racing & Fencing Fixes

## Problem Statement

With multiple FastAPI main-thread instances (e.g. ports 8432–8435) each capable of dispatching and running LangGraph graph threads, the following races were identified:

### Race A — Dual steal (Fix 1)
Two instances simultaneously see a dead lock owner, both call `steal_lock`, and the old unconditional `SET` means both succeed.  Both instances dispatch graphs for the same `thread_id` and run concurrently.

### Race B — Zombie continuation after lock renewal failure (Fix 2)
When a renewal heartbeat (`PEXPIRE`) fails because the lock TTL has already expired and another instance has taken over, the previous code only logged the failure and let the graph keep running.  The zombie instance continued writing nodes and tasks while the new owner's graph was also advancing.

### Race C — No DB-level write rejection (Fix 5)
Even with A and B fixed, there is a short window between lock expiry and the zombie detecting the loss.  Any DB writes (node upsert, task insert) that the zombie emitted before aborting are stamped with the same thread-scoped data and could overwrite the new owner's rows or leave orphaned `running` rows indefinitely (Fix 3 / Fix 5 addresses this).

---

## Root Cause Analysis

| # | What went wrong | Affected code |
|---|-----------------|---------------|
| A | `steal_lock` used unconditional `SET` — no compare-and-swap on the dead owner | `main_thread/lock.py` |
| B | Renewal loop did nothing on failure; zombie graph continued | `main_thread/executor.py:_renew_lock_loop` |
| C | `tasks` rows have random UUID primary keys — two concurrent runs insert two distinct rows; no way to tell which belongs to the zombie | `fin_agents.tasks`, `tasks/sql.py` |

### Why Redis shard consistency is not the issue
`shard_for_thread(thread_id)` = `SHA-256(thread_id) % n` is deterministic and identical on all instances.  Both the lock key and fencing counter for any `thread_id` land on the same Redis node.  The races above exist at the application protocol level, not at the Redis routing level.

---

## Fixes Implemented

### Fix 1 — CAS `steal_lock`

**File**: `backend/main_thread/lock.py`

`steal_lock(thread_id, dead_owner)` now uses Lua `_STEAL_CAS_SCRIPT`:
```
GET lock → compare port+pid vs dead_owner → only if match: INCR fencing_counter, SET new lock, return token
```
If the stored owner has already changed (another instance stole it first), the script returns `nil`.  The caller in `dispatch_graph_run` sees `None` → re-checks the new owner → raises `ThreadRoutingError` to route to the actual new owner.

`acquire_lock` was similarly rewritten as an atomic Lua script (`_ACQUIRE_SCRIPT`) combining the `GET`, `INCR fencing_counter`, and `SET NX` into a single atomic operation so no partial acquire is possible.

Return type changed: both functions now return `int | None` (the fencing token) instead of `bool / None`.

### Fix 2 — Cancel graph on lock renewal failure

**File**: `backend/main_thread/executor.py`

`_renew_lock_loop` accepts a new `lock_lost_event: asyncio.Event` parameter.  When `renew_lock` returns `False`:
1. Sets `lock_lost_event`.
2. Calls `task.cancel()` on the running graph asyncio.Task (fetched from the registry).
3. Exits the loop.

`_run_graph` has a dedicated `except asyncio.CancelledError` block that checks `lock_lost_event.is_set()`:
- **If set** (lock-loss abort): logs the zombie abort at `ERROR` level with error code `MT_LOCK_LOST`, does **not** call `complete_thread(failed=True)` (the new owner will complete it), then falls through to `finally` for cleanup.
- **If not set** (other cancellation such as uvicorn shutdown): re-raises so the normal cancellation path handles it.

### Fix 3 — Zombie task cleanup

**File**: `backend/langgraph/lifecycle/threads/nodes/tasks/ops.py`  
**File**: `backend/langgraph/lifecycle/threads/nodes/tasks/sql.py`

New `cleanup_zombie_tasks(thread_id, fencing_token)` function.  Called in `_run_graph`'s `finally` block when `lock_lost_event` is set and `fencing_token > 0`:

```sql
UPDATE fin_agents.tasks
SET status = 'wrong', updated_at = NOW()
WHERE thread_id = %s
  AND fencing_token = %s
  AND status NOT IN ('completed', 'failed', 'cancelled', 'wrong')
RETURNING task_id
```

Only this zombie run's tasks are affected (exact `fencing_token` match).  The new owner's tasks have a higher token so they are untouched.  `'wrong'` is a terminal status that blocks all further updates from Celery workers.

### Fix 5 — Fencing tokens (DB-level zombie write rejection)

**Files**: `main_thread/lock.py`, `main_thread/context.py`, `nodes/sql.py`, `tasks/sql.py`, `nodes/ops.py`, `tasks/ops.py`, `sql/fin_agents.sql`

#### Redis side
`acquire_lock` and `steal_lock` atomically increment `fin:thread:fencing:{thread_id}` in the same Lua script that writes the lock.  The counter is returned as the fencing token and stored in the lock value: `{"port":8432,"pid":12345,"token":7}`.

#### ContextVar propagation
`backend/main_thread/context.py` exposes `set_fencing_token(token)` / `get_fencing_token()` backed by a `ContextVar[int]` (default 0).  `_run_graph` calls `set_fencing_token(fencing_token)` once at the start; Python asyncio automatically propagates the context to all sub-coroutines created within the same task (including LangGraph's internal machinery), so every lifecycle write within a graph run inherits the correct token without any parameter threading.

#### DB schema
```sql
-- nodes table
fencing_token BIGINT NOT NULL DEFAULT 0

-- tasks table
fencing_token BIGINT NOT NULL DEFAULT 0
```

#### Node upsert guard (`_UPSERT_NODE`)
```sql
ON CONFLICT (node_id) DO UPDATE
SET status = CASE
               WHEN excluded.fencing_token < fin_agents.nodes.fencing_token THEN nodes.status  -- zombie rejected
               WHEN nodes.status IN ('completed','failed','cancelled','wrong') THEN nodes.status
               ELSE 'running'
             END,
    input  = CASE
               WHEN excluded.fencing_token < fin_agents.nodes.fencing_token THEN nodes.input  -- zombie rejected
               ELSE EXCLUDED.input
             END,
    fencing_token = GREATEST(excluded.fencing_token, fin_agents.nodes.fencing_token)
```

#### Node complete guard (`_UPDATE_NODE_COMPLETED`)
```sql
WHERE node_id = %s AND thread_id = %s
  AND status NOT IN ('completed','failed','cancelled','wrong')
  AND fencing_token = %s   -- zombie writes (different token) produce 0 rows
```

The `0 rows updated` result is treated as "already terminal" (existing log path) and SSE is suppressed — no false SSE events from zombie completions.

---

## Error Codes Added

| Code | Meaning |
|------|---------|
| `MT_LOCK_LOST` | Renewal failed; zombie run aborted; new owner will complete the thread |
| `MT_STEAL_RACE` | CAS steal failed; another instance already stole the lock; routing to new owner |

---

## Invariants After the Fix

1. At most one CAS steal winner per `thread_id` per generation (Lua atomicity).
2. Zombie graphs cancel within one renewal interval (≤ `THREAD_LOCK_RENEW_INTERVAL_SECONDS`, default 25 s).
3. All node writes from a zombie run are rejected at the DB layer if the new owner has already upserted a higher-token row.
4. All task rows from a zombie run are marked `'wrong'` in the zombie's `finally` block even if the new owner has not touched them yet.
5. `complete_thread` is idempotent (terminal status guard on `user_queries`): the first writer wins; the zombie's deferred call (if it somehow reaches it) is a no-op.

---

## Files Changed

| File | Change |
|------|--------|
| `backend/main_thread/context.py` | New — `ContextVar` for fencing token |
| `backend/main_thread/lock.py` | CAS `steal_lock`, atomic `acquire_lock`, `OwnerInfo.token` field |
| `backend/main_thread/executor.py` | Fix 1 token plumbing, Fix 2 zombie abort, Fix 3 cleanup call |
| `backend/main_thread/errors/__init__.py` | `MT_LOCK_LOST`, `MT_STEAL_RACE` error codes |
| `backend/langgraph/lifecycle/threads/nodes/sql.py` | Fencing in `_UPSERT_NODE` and `_UPDATE_NODE_COMPLETED` |
| `backend/langgraph/lifecycle/threads/nodes/ops.py` | Read token from context; pass to SQL |
| `backend/langgraph/lifecycle/threads/nodes/tasks/sql.py` | Fencing in `_INSERT_TASK`; new `_CLEANUP_ZOMBIE_TASKS` |
| `backend/langgraph/lifecycle/threads/nodes/tasks/ops.py` | Fencing in `create_task`; new `cleanup_zombie_tasks` |
| `backend/langgraph/lifecycle/threads/nodes/tasks/__init__.py` | Export `cleanup_zombie_tasks` |
| `backend/langgraph/lifecycle/__init__.py` | Export `cleanup_zombie_tasks` |
| `sql/fin_agents.sql` | `fencing_token BIGINT NOT NULL DEFAULT 0` on `nodes` and `tasks` |
