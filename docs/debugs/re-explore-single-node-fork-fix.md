# Re-explore "got just one node run" — Root Cause & Fix

## Symptom

When re-exploring a node (e.g. `analyze_stats_node`), only `conclusion_node v1`
appeared in the DB.  The fork-point itself never ran its Python code.  Similarly,
when re-exploring `apac_analyze_node`, all downstream nodes (research, stats,
news, conclusion) produced a new version but `apac_analyze_node` itself did not.

## Root Cause: `as_node=fork_point_name` in `aupdate_state`

`backend/users/queries/re_explore.py` was calling:

```python
updated_config = await graph.aupdate_state(fork_config, state_update, as_node=fork_point_name)
```

### What `aupdate_state(as_node=X)` actually does

LangGraph's `aupdate_state` with `as_node=X`:
1. Runs node X's *writers* (channel-update lambdas that record X's writes).
2. Fires X's *outgoing edges*, bumping the trigger channels for X's successors.
3. Creates a new checkpoint whose `next` = the nodes AFTER X.

So `as_node=fork_point_name` marks the fork-point as **already executed** and
places the fork-point's *successors* in `next`.  When `ainvoke` runs the new
checkpoint it starts at those successors — the fork-point's own Python code is
never invoked.

### Concrete example

- Target snapshot (step-2): `next = ("analyze_stats_node", "analyze_news_node")`
- `aupdate_state(as_node="analyze_stats_node")` at step-2:
  - Stats's writers run → stats→conclusion trigger fires
  - New `next = ("analyze_news_node",)`
  - `ainvoke`: news runs (parallel-sibling shortcircuit, no DB row), conclusion runs (v1)
  - `analyze_stats_node` **never ran** — only `conclusion_node v1` in DB ✓ matches symptom

## Fix: Use `as_node=None` (let LangGraph infer the predecessor)

The correct `as_node` is the **predecessor** of the fork-point, not the fork-point
itself.  With `as_node=None`, LangGraph inspects the checkpoint's `versions_seen`
dict to find the node that last modified state — that node becomes the implicit
writer, its outgoing edges fire, and `fork_point_name` stays in `next`.

```python
# After fix — fork_point stays in `next`, ainvoke actually runs it
updated_config = await graph.aupdate_state(fork_config, state_update)
```

`ainvoke` then sees `fork_point_name` in `next`, runs it with `fork_generation=N`
set in state, the node's `is_forked=True` guard triggers, and a new DB row is
written.

### Fan-in exception: `InvalidUpdateError("Ambiguous update")`

For `conclusion_node` (triggered by BOTH `analyze_stats_node` and
`analyze_news_node` in the same superstep), `versions_seen` has both parallel
nodes at the same channel version — LangGraph cannot determine which was "last"
and raises `InvalidUpdateError("Ambiguous update")`.

Fix: catch this error, find one direct predecessor of the fork-point from the
compiled graph topology, and retry with that explicit `as_node`:

```python
try:
    updated_config = await graph.aupdate_state(fork_config, state_update)
except InvalidUpdateError as e:
    if "Ambiguous" not in str(e):
        raise
    _edges = graph.get_graph().edges          # public DrawableGraph API
    _predecessors = [
        edge.source for edge in _edges
        if edge.target == fork_point_name
        and edge.source not in ("__start__", "__end__")
    ]
    if not _predecessors:
        raise
    updated_config = await graph.aupdate_state(
        fork_config, state_update, as_node=_predecessors[0]
    )
```

Why `_predecessors[0]` (e.g. `analyze_stats_node`) works for `conclusion_node`:
- `aupdate_state(as_node="analyze_stats_node")` bumps c_stats trigger (V_stats+1).
- The c_news trigger is **already** above conclusion's last-seen version from the
  original parallel run (V_news > versions_seen["conclusion_node"]["c_news"]).
- Both trigger conditions satisfied → `conclusion_node` remains in `next` → runs.

## Graph topology (for reference)

```
START → query_node → (cond:region) → [apac|emea|amer]_analyze_node
    → research_subgraph → analyze_stats_node ─┐
                        → analyze_news_node  ─┴→ conclusion_node → END
```

`research_subgraph` triggers both parallel analysis nodes in the same superstep.

## Files Changed

- `backend/users/queries/re_explore.py` — replaced `as_node=fork_point_name` with
  the try/except pattern described above; moved `InvalidUpdateError` import to
  module level.

## DB Evidence (thread `3ec8b74f`)

| version | nodes in DB | expected |
|---------|-------------|---------|
| v0 | query, apac_analyze, research, stats, news, conclusion | ✓ |
| v1 | **conclusion only** (is_forked=False) | bug — should have been conclusion v1 is_forked=True |
| v2 | research, stats, news, conclusion (missing apac_analyze) | bug — apac_analyze should be v2 is_forked=True |

Both v1 and v2 show the classic pattern: the fork-point itself was skipped.
