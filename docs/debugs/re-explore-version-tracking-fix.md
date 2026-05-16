# Re-explore Version Tracking Fix

## Symptoms

After clicking "Re-explore" on a completed node:
1. Version dropdown never appeared in the Node Graph card header
2. NodeDetail showed tasks from ALL versions of the same node merged together (e.g., 2× "apac_analyze" tasks)
3. Timeline spanned the full wall-clock range including idle time between runs

## Root Cause 1 — Backend: `aupdate_state` return value discarded

`re_explore_node` in `backend/users/queries.py` called:

```python
await graph.aupdate_state(fork_config, state_update)
# ... then dispatched with the original fork_config (unchanged)
await dispatch_graph_run(thread_id, f"__fork__:{_json.dumps(fork_config)}")
```

LangGraph's `aupdate_state` **creates a new child checkpoint** containing the updated state values (including `fork_generation: N`) and returns the config pointing at that new checkpoint's `checkpoint_id`.  The original `fork_config` still points to the pre-update checkpoint.

When the graph was dispatched with the old `fork_config`, it resumed from the checkpoint **before** the `fork_generation` update, so:
- All nodes read `state.get("fork_generation", 0)` → 0
- `make_node_id(thread_id, node_name, 0)` → same UUID5 as the original run
- Re-explored nodes wrote to the same DB row (same `node_id`) as the original nodes
- `version` stayed 0 for every node in every run
- `maxVersion` never exceeded 0 → version dropdown never shown

**Fix:**
```python
updated_config = await graph.aupdate_state(fork_config, state_update)
await dispatch_graph_run(thread_id, f"__fork__:{_json.dumps(updated_config)}")
```

## Root Cause 2 — Frontend: task filter uses `node_name` fallback

`NodeDetail/index.tsx` filtered tasks with:

```typescript
const nodeTasks = tasks.filter(
  (t) => t.node_id === node.node_id || t.node_name === node.node_name,
);
```

The `|| t.node_name === node.node_name` fallback matched tasks from ALL versions of the same logical node (same `node_name` but different `node_id` UUID5).  With re-explore in place, viewing v0's `apac_analyze_node` would also show all v1 `apac_analyze` tasks.

**Fix:**
```typescript
const nodeTasks = tasks.filter((t) => t.node_id === node.node_id);
```

All tasks are created via `create_task(ctx)` which always sets `node_id = ctx.node_id` (the UUID5), so strict `node_id` filtering is safe.

## DB Observation

After the buggy re-explore, the DB showed two completed `apac_analyze` tasks for the same `node_id` (same UUID5, version=0):

```
node_id: f7557207-1ca3-515c-97d1-1df239b6c790  version=0  is_forked=false
  → task d659cc38  apac_analyze  completed
  → task 72c94fd1  apac_analyze  completed
```

Both runs created tasks for the same `node_id` because both read `fork_generation=0`.  After the fix, re-explore creates a new node_id with `version=1` so the original and forked runs are properly separated.

## Timeline Issue

Timeline spanning too long was a downstream consequence of root cause 1: since re-explored nodes had `version=0` and the same `node_id`, the timeline included both runs' timestamps (potentially hours apart) in the same span. With proper version tracking:
- `getNodesForVersion(allNodes, 1)` returns shared v0 predecessors + v1 fork nodes
- The gap between the shared predecessor's end time and the fork node's start time is detected by `gapInfo` (> 2s threshold)
- The timeline compresses the gap and shows a dashed separator line
