"""graph.governance — execution hierarchy registry and lifecycle publisher.

Tracks the three-level execution tree for every LangGraph thread in Redis
and provides a publisher that emits terminal lifecycle events to all live
leaf streams when a thread ends or is cancelled.

Hierarchy
---------
::

    thread_id  (top-level — LangGraph thread / user query)
      └─ node_id  (mid-level — LangGraph node execution)
           └─ stream_id  (leaf-level — Celery task / background work unit)

Usage — registration (in leaf workers)
---------------------------------------
::

    from backend.graph.governance import register_stream, deregister_stream

    await register_stream(thread_id, node_id, stream_id)
    try:
        ...  # do work
    finally:
        await deregister_stream(thread_id, node_id, stream_id)

Usage — terminal propagation (in runner / cancel handler)
-----------------------------------------------------------
::

    from backend.graph.governance import publish_governance_end

    await publish_governance_end(thread_id, reason="cancelled")
"""

from backend.graph.governance.registry import (
    deregister_stream,
    get_streams_for_node,
    get_streams_for_thread,
    register_stream,
)
from backend.graph.governance.publisher import publish_governance_end

__all__ = [
    "register_stream",
    "deregister_stream",
    "get_streams_for_node",
    "get_streams_for_thread",
    "publish_governance_end",
]
