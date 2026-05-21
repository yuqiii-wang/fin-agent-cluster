"""StateUtilsMixin — GraphState inspection and NodeRecord construction."""

from __future__ import annotations

from typing import Any

from backend.langgraph.state import GraphState, NodeRecord


class StateUtilsMixin:
    """Mixin for reading from GraphState and building NodeRecord dicts.

    Methods:
        _find_node_id_by_name : Locate a node_id in state by node_name.
        _build_node_record    : Construct a NodeRecord for state insertion.
    """

    @staticmethod
    def _find_node_id_by_name(state: GraphState, node_name: str) -> str | None:
        """Look up a node_id from the current nodes dict by node_name.

        Scans ``state["nodes"]`` for a record whose metadata.node_name matches.
        Used by downstream nodes to find their predecessor's node_id so they
        can call ``read_node_output(node_id)``.

        Args:
            state:     Current GraphState.
            node_name: The ``node_name`` to search for.

        Returns:
            The matching node_id string, or ``None`` if not found.
        """
        for node_id, record in (state.get("nodes") or {}).items():
            meta = record.get("metadata") or {}
            if meta.get("node_name") == node_name:
                return node_id
        return None

    def _build_node_record(
        self,
        node_id: str,
        version: int,
        prev_node_ids: list[str],
        status: str,
    ) -> NodeRecord:
        """Build a NodeRecord dict for insertion into ``GraphState.nodes``.

        Args:
            node_id:       UUID string for this node.
            version:       Fork generation counter.
            prev_node_ids: IDs of predecessor nodes.
            status:        Node lifecycle status string.

        Returns:
            A NodeRecord TypedDict.
        """
        return NodeRecord(
            node_id=node_id,
            task_ids=[],
            metadata={
                "node_name": self.node_name,  # type: ignore[attr-defined]
                "type": str(self.node_type),  # type: ignore[attr-defined]
                "status": status,
                "version": version,
            },
            prev_node_ids=prev_node_ids,
            next_node_ids=[],
        )


__all__ = ["StateUtilsMixin"]
