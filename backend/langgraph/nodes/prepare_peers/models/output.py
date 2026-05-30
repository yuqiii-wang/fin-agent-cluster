"""Output model for prepare_peers node."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["AnalyzePeersOutput"]


class AnalyzePeersOutput(BaseModel):
    """Typed output for ``prepare_peers``.

    Persisted to ``fin_agents.node_executions`` for downstream nodes.

    Attributes:
        proposed_peers: Peer ticker symbols proposed by the LLM for the target stock.
    """

    proposed_peers: list[str] = Field(
        default_factory=list,
        description="Peer ticker symbols proposed by the LLM.",
    )
