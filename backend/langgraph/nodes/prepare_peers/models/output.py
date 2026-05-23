"""Output model for prepare_peers node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

__all__ = ["AnalyzePeersOutput"]


class AnalyzePeersOutput(BaseModel):
    """Typed output for ``prepare_peers``.

    Persisted to ``fin_agents.node_executions`` for downstream nodes.

    Attributes:
        df_splits:     Per-symbol OHLCV DataFrame for StackCandleStick rendering.
                       Target appears first, then confirmed peers.
                       Shape: [{"symbol": str, "label": str, "df_split": DfSplitDict}, ...].
        corr_df_split: Correlation metrics DataFrame in pandas split-orient.
                       index = confirmed peer symbols; columns = [close_corr,
                       sma_20_corr, sma_50_corr, ema_12_corr, ema_26_corr].
                       Only columns with at least one non-None value are included.
    """

    df_splits: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Per-symbol OHLCV df_splits (target first, then peers) for StackCandleStick.",
    )
    corr_df_split: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Correlation metrics DataFrame (pandas split-orient): "
            "index=peer_symbols, columns=[close_corr, sma_20_corr, sma_50_corr, ema_12_corr, ema_26_corr]."
        ),
    )
