"""Node metadata endpoint helpers — GET /api/v1/graph/node-metas.

Returns structured metadata for every production graph node plus a
``__global__`` virtual entry that represents graph-wide defaults.

The per-node ``config_fields`` are read directly from each node class's
``config_fields`` class variable, so adding or changing a field on a node
class is immediately reflected in the API response without touching this file.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


class SelectOption(BaseModel):
    """A single option in a ``select`` config field."""

    value: str
    label: str


class NodeConfigField(BaseModel):
    """Metadata for one user-configurable field on a graph node.

    Mirrors ``NodeConfigField`` in the frontend ``nodeMeta`` shape so the
    frontend can drive the preferences UI entirely from this response.
    """

    key: str
    label: str
    type: Literal["boolean", "select", "number"]
    options: Optional[list[SelectOption]] = None
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    description: str


class NodeMetaResponse(BaseModel):
    """Metadata for a single graph node exposed to the preferences UI."""

    node_name: str
    display_name: str
    category: str
    fields: list[NodeConfigField]


# ---------------------------------------------------------------------------
# __global__ entry — represents graph-wide default preferences
# ---------------------------------------------------------------------------

_GLOBAL_META = NodeMetaResponse(
    node_name="__global__",
    display_name="Global (all nodes)",
    category="Global",
    fields=[
        NodeConfigField(
            key="human_in_the_loop",
            label="Human-in-the-loop (default)",
            type="boolean",
            description="Default review gate applied to all nodes unless overridden per-node.",
        ),
    ],
)


def _parse_field(raw: dict[str, Any]) -> NodeConfigField:
    """Convert a raw config_fields dict entry to a :class:`NodeConfigField`."""
    options: Optional[list[SelectOption]] = None
    if raw.get("options"):
        options = [SelectOption(**o) for o in raw["options"]]
    return NodeConfigField(
        key=raw["key"],
        label=raw["label"],
        type=raw["type"],
        options=options,
        min=raw.get("min"),
        max=raw.get("max"),
        step=raw.get("step"),
        description=raw["description"],
    )


def get_node_metas() -> list[NodeMetaResponse]:
    """Build the full node-metas list from NODE_REGISTRY + the global entry.

    Returns:
        List starting with ``__global__``, followed by one entry per
        production node that declares ``config_fields``.
    """
    from backend.langgraph.nodes import NODE_REGISTRY

    result: list[NodeMetaResponse] = [_GLOBAL_META]
    for node in NODE_REGISTRY.values():
        if not node.config_fields:
            continue
        result.append(
            NodeMetaResponse(
                node_name=node.node_name,
                display_name=node.display_name or node.node_name,
                category=node.category,
                fields=[_parse_field(f) for f in node.config_fields],
            )
        )
    return result


__all__ = ["NodeConfigField", "NodeMetaResponse", "SelectOption", "get_node_metas"]
