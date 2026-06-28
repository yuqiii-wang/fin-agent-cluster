"""Output model for load_peers_stats node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from backend.quant.stats import STATS_VIEW_TYPE

__all__ = ["LoadPeersStatsOutput", "PeerStatsResult"]


class PeerStatsResult(BaseModel):
    """OHLCV stats result for a single proposed peer.

    Attributes:
        symbol:        Peer ticker symbol, e.g. ``'MSFT'``.
        rows_upserted: Number of bar rows written to ``fin_markets.quant_stats``.
        granularity:   Bar granularity (e.g. ``'1day'``).
        source:        Provider source label (e.g. ``'yfinance'``).
        from_cache:    Whether the raw stats were served from cache.
    """

    symbol: str = Field(description="Peer ticker symbol, e.g. 'MSFT'.")
    rows_upserted: int = Field(description="Bar rows written to quant_stats.")
    granularity: str = Field(description="Bar granularity, e.g. '1day'.")
    source: str = Field(description="Provider source label, e.g. 'yfinance'.")
    from_cache: bool = Field(
        default=False,
        description="Whether raw stats were served from cache.",
    )


class LoadPeersStatsOutput(BaseModel):
    """Typed output for ``load_peers_stats``.

    Persisted to ``fin_agents.node_executions`` for downstream nodes.

    Attributes:
        peers:       Per-peer OHLCV stats results.
        period:      Aggregation period used for all peers.
        df_splits:   Per-symbol OHLCV df_split payloads for StackCandleStick rendering.
        stats_views: Node-level stats view types; always ``["StackCandleStick"]``.
    """

    peers: list[PeerStatsResult] = Field(
        default_factory=list,
        description="Per-peer OHLCV stats results.",
    )
    period: str = Field(description="Aggregation period used for all peers.")
    df_splits: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Per-symbol OHLCV df_splits for StackCandleStick rendering.",
    )
    stats_views: list[str] = Field(
        default_factory=lambda: [STATS_VIEW_TYPE.STACK_CANDLE_STICK.value],
        description="Node-level stats view types.",
    )
