# Recovery failures and NodeType warning on server restart

## Symptoms

```
ERROR [main_thread.startup] found N running thread(s) to evaluate for recovery
# No follow-up "dispatched recovery ..." log — threads stay stuck 'running' forever.

WARNING langgraph.checkpoint.serde.jsonplus
  Deserializing unregistered type backend.db.postgres.types.NodeType from checkpoint.
```

---

## Bug 1 — `MAIN_THREAD_PORT` was never populated by `run.py`

### Root Cause

`run.py` sets the env var **`FASTAPI_PORT`** per instance (8432, 8433, …) but
`this_owner()` in `lock.py` read **`MAIN_THREAD_PORT`**, which has a hardcoded
default of `8432` and is **never** set by `run.py`.

Result: every instance (8432, 8433, 8434, …) stamped its Redis lock with
`"port": 8432`, so the `port` field was useless as an instance differentiator.
All ownership checks (`is_mine`) fell back to PID comparison only.

### Fix — `backend/main_thread/lock.py`

Changed `this_owner()` to use `get_settings().FASTAPI_PORT`:

```python
return OwnerInfo(port=get_settings().FASTAPI_PORT, pid=os.getpid(), token=0)
```

Also removed the now-dead `MAIN_THREAD_PORT` field from `backend/config.py`.

---

## Bug 2 — `check_owner_alive` TCP check fooled by same-port restart

### Root Cause

`check_owner_alive` used a plain TCP connect to `127.0.0.1:{owner["port"]}`.
After a hot-reload or restart, the **new** process listens on the **same port**.
`asyncio.open_connection` succeeds, returns `True`, and both
`startup.recover_running_threads` and `dispatch_graph_run` conclude the old
dead owner is still alive — so recovery is skipped.

Timeline:
1. Old process (pid=A, port=8432) crashes / restarts.
2. New process (pid=B, port=8432) starts → acquires port 8432.
3. New process startup finds DB threads still `'running'`.
4. Old lock value: `{"port": 8432, "pid": A, ...}`.
5. `is_mine`: port matches, PID differs → `False`.
6. `check_owner_alive(old_owner)`: TCP to 8432 succeeds (new process B is
   there) → returns `True`.
7. `startup.py` does `continue` — **no recovery dispatched**.
8. The thread stays stuck `'running'` indefinitely (until next restart).

### Fix — `backend/main_thread/lock.py`

Added `_pid_alive(pid)` helper that calls `os.kill(pid, 0)` (signal-0 sends no
signal but detects PID existence on Linux/WSL2).

Updated `check_owner_alive` to a two-step check:
1. TCP connect — if the port isn't responding, dead.
2. `_pid_alive(owner["pid"])` — if the port IS responding but the original PID
   is gone, the port is occupied by a replacement process → return `False`.

```python
async def check_owner_alive(owner: OwnerInfo) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", owner["port"]), timeout=...
        )
        writer.close()
        await writer.wait_closed()
        return _pid_alive(owner["pid"])   # <-- new
    except Exception:
        return False
```

Multi-instance safety: if instance on port 8433 checks a lock for port 8432
that was restarted, it also benefits — TCP to 8432 succeeds (new process), but
`_pid_alive(old_pid_8432)` returns False → recovery proceeds correctly.

---

## Bug 3 — `NodeType` StrEnum stored as enum object in LangGraph checkpoint

### Root Cause

`_make_node_record` in `base/node.py` put `self.node_type` (a `NodeType`
StrEnum instance) directly into the `metadata["type"]` field of the
`NodeRecord`. LangGraph's msgpack serializer detected an unregistered Python
type and logged a warning. This will become a hard error in future LangGraph
versions.

### Fix — `backend/langgraph/nodes/base/node.py`

Cast to plain string at insertion time:

```python
"type": str(self.node_type),   # was: self.node_type
```

Since `NodeType` is a `StrEnum`, `str(NodeType.WORKFLOW)` returns `"Workflow"`.
The checkpoint now stores a plain string, so no deserialisation type lookup
is needed on resume.
