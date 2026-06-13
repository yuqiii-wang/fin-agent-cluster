"""StateUtilsMixin -- GraphState inspection and NodeRecord construction."""

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
        When multiple versions of the same node exist (e.g. original v0 and a
        re-explore v1 both in state from checkpoint accumulation), returns the
        node_id for the **highest version** so downstream nodes always read
        from the most recent completed execution.

        Args:
            state:     Current GraphState.
            node_name: The ``node_name`` to search for.

        Returns:
            The matching node_id string for the highest-version record,
            or ``None`` if not found.
        """
        best_id: str | None = None
        best_version: int = -1
        for node_id, record in (state.get("nodes") or {}).items():
            meta = record.get("metadata") or {}
            if meta.get("node_name") == node_name:
                v = meta.get("version", 0)
                if v > best_version:
                    best_version = v
                    best_id = node_id
        return best_id

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
