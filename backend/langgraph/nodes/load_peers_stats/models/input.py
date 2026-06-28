"""Input model for load_peers_stats node."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["LoadPeersStatsInput"]


class LoadPeersStatsInput(BaseModel):
    """Typed input for ``load_peers_stats``.

    Read from ``prepare_peers``'s ``node_executions`` row via the PG replica.

    Attributes:
        peers:  List of peer ticker symbols proposed by ``prepare_peers``.
        period: OHLCV aggregation period, e.g. ``'1mo'``, ``'1y'``.
    """

    peers: list[str] = Field(
        default_factory=list,
        description="Peer ticker symbols proposed by prepare_peers.",
    )
    period: str = Field(default="1y", description="OHLCV aggregation period.")
