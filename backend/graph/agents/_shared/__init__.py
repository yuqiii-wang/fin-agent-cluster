"""_shared — shared nodes and errors available to all graph agents.

Sub-packages:
    errors — shared error codes for mock pipeline nodes.
    models — base Pydantic models (NodeBaseInput/Output, TaskBaseInput/Output).
    nodes  — re-usable LangGraph node functions (each node owns its tasks).
"""

from backend.graph.agents._shared import errors, models, nodes

__all__ = ["errors", "models", "nodes"]
