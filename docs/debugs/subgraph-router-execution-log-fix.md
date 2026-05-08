# Debug: Subgraph Router + execution_log Duplicate Functions

**Date:** 2026-05-07  
**Symptoms:** All graph executions fail with `unhashable type: 'dict'`; earlier runs failed with `upsert_node_record() missing 2 required positional arguments`.

---

## Issue 1 — `upsert_node_record` signature mismatch (resolved)

**Error:**
```
TypeError: upsert_node_record() missing 2 required positional arguments: 'node_execution_id' and 'executed_at'
```

**Root cause:** `execution_log.py` contained duplicate function definitions.  The old `finish_node_execution` (first definition) called `upsert_node_record(node_name, status, node_execution_id, ended_at)` — wrong positional order and missing `node_id` / `thread_id`.  A new correct version (last definition in file) was added later but the old dead copy remained.  Python uses the last definition, so the correct version was active.  However, the stale first copy created maintenance risk and confused the error trail.

**Fix:** Removed the four duplicate stale function bodies (`start_node_execution`, `finish_node_execution`, `update_node_execution_status`, `log_node_execution`) — lines 131–358 in the original file.

---

## Issue 2 — `unhashable type: 'dict'` in LangGraph router (critical)

**Error:**
```
File "langgraph/graph/_branch.py", line 203, in _finish
    r if isinstance(r, Send) else self.ends[r] for r in result
TypeError: unhashable type: 'dict'
```

**Root cause:** `_route_query` in `builder.py` returned **compiled `StateGraph` objects** instead of node name strings.  In newer LangGraph, `_branch._finish` iterates `result` (the router's return value) and tries `self.ends[r]`.  If `result` is a compiled graph that is iterable (or yields dict-like objects internally), `r` becomes a dict and the hash lookup fails.

The conditional edges were also wired with a path map using compiled graph objects as keys:
```python
{graph: name for name, graph in subgraphs.items()}   # compiled_graph → node_name
```
This is fragile against LangGraph internals and unnecessary.

**Fix:** Changed `_route_query` to return the **node name string** directly (`"mock_perf_subgraph"`, `"mock_single_subgraph"`, `"fin_analyst_subgraph"`), and removed the path map from `add_conditional_edges`.  LangGraph resolves string node names without needing an intermediary map.

```python
# Before
def _route_query(subgraphs):
    def _router(state) -> Any:
        return subgraphs["mock_perf_subgraph"]  # compiled graph object

# After  
def _route_query():
    def _router(state) -> str:
        return "mock_perf_subgraph"  # string node name
```

---

## Impact

Both issues caused 100% failure rate for all query types.  After fix, all three routes (`mock_perf_subgraph`, `mock_single_subgraph`, `fin_analyst_subgraph`) resolve correctly and the `done` event is emitted on completion.
