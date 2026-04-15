"""Quant task output models for market_data_collector.

Each model represents the JSON-structured result of one quant sub-task.
All models include a ``to_context_lines()`` method that renders human-readable
lines suitable for injection into the LLM synthesis prompt.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class OHLCVWindowResult(BaseModel):
    """Output of one OHLCV window fetch task.

    Task: ``ohlcv_<granularity>`` — parallel across windows.
    Input:  ticker, OhlcvWindow config, region.
    Output: OHLCV bars (empty when DB is already fresh).
    """

    ticker: str = Field(..., description="Ticker symbol")
    window: str = Field(..., description="Granularity key, e.g. '15min', '1day'")
    label: str = Field("", description="Human-readable label for context")
    bars: list[dict] = Field(default_factory=list, description="OHLCV bars as JSON dicts")
    source: str = Field("", description="Data provider used")
    error: Optional[str] = Field(None, description="Error message if fetch failed")

    def to_context_lines(self) -> list[str]:
        """Render OHLCV window as context lines for LLM synthesis."""
        if self.error:
            return []
        if not self.bars:
            return [f"\n{self.label}: up-to-date in DB."]
        lines = [f"\n{self.label} — {len(self.bars)} new bars (last 3):"]
        for bar in self.bars[-3:]:
            lines.append(
                f"  {bar['date']}: O={bar['open']:.2f} H={bar['high']:.2f} "
                f"L={bar['low']:.2f} C={bar['close']:.2f} V={bar['volume']:,}"
            )
        return lines


class MacroResult(BaseModel):
    """Output of a single macro commodity/rate ticker fetch task.

    Task: ``macro_<key>`` — parallel across all MACRO_SYMBOLS keys.
    Input:  yfinance/Stooq symbol + human-readable label.
    Output: 1-year daily OHLCV summary.
    """

    key: str = Field("", description="MACRO_SYMBOLS key, e.g. 'gold', 'crude_oil'")
    symbol: str = Field(..., description="Ticker symbol, e.g. 'GC=F'")
    label: str = Field(..., description="Human-readable label, e.g. 'Gold ($/oz)'")
    latest_bar_date: Optional[str] = Field(None, description="Date of the most recent OHLCV bar")
    latest_bar: Optional[dict] = Field(None, description="Most recent OHLCV bar as JSON dict")
    move_5d_pct: Optional[float] = Field(None, description="5-day price move (%)")
    move_1y_pct: Optional[float] = Field(None, description="1-year price move (%)")
    bars_count: int = Field(0, description="Number of daily bars fetched")
    source: str = Field("", description="Data provider used")
    error: Optional[str] = Field(None, description="Error message if fetch failed")
    # Raw OHLCVBar objects — excluded from model_dump/JSON so they never enter
    # LLM context or graph state; only used in-process for chart output.
    bars: list = Field(default_factory=list, exclude=True, description="Raw OHLCVBar list (in-process only)")

    def to_context_lines(self) -> list[str]:
        """Render macro result as context lines for LLM synthesis."""
        if self.error:
            return [f"\n=== {self.label} ({self.symbol}) — data unavailable ==="]
        if self.bars_count == 0:
            return [f"\n=== {self.label} ({self.symbol}) — no data ==="]
        lines = [
            f"\n=== {self.label} ({self.symbol}) — {self.source} ({self.bars_count} daily bars, 2y) ===",
        ]
        if self.latest_bar and self.latest_bar_date:
            b = self.latest_bar
            lines.append(
                f"  Latest bar: {self.latest_bar_date[:10]}  "
                f"O={b['open']:.4f} H={b['high']:.4f} L={b['low']:.4f} C={b['close']:.4f}"
            )
        if self.move_5d_pct is not None:
            lines.append(f"  5-day move: {self.move_5d_pct:+.2f}%")
        if self.move_1y_pct is not None:
            lines.append(f"  1-year move: {self.move_1y_pct:+.2f}%")
        return lines


class BondResult(BaseModel):
    """Output of US Bond yield curve fetch task.

    Task: ``bond`` — parallel.
    Input:  QuantClient + thread_id.
    Output: 2y daily OHLCV bars per tenor (1-month, 6-month, 5-year, 10-year).
    """

    tenors: list[OHLCVWindowResult] = Field(default_factory=list, description="Per-tenor 2y daily OHLCV")
    error: Optional[str] = Field(None, description="Error message if overall fetch failed")

    def to_context_lines(self) -> list[str]:
        """Render Bond yield curve as context lines for LLM synthesis."""
        if self.error:
            return [f"\n=== US Bond Yield Curve — data unavailable: {self.error} ==="]
        lines: list[str] = ["\n=== US Bond Yield Curve (2y daily) ==="]
        for tenor in self.tenors:
            lines.extend(tenor.to_context_lines())
        return lines


class QuantCollectionResult(BaseModel):
    """Aggregated quant task output for a single market_data_collector run."""

    ohlcv_windows: list[OHLCVWindowResult] = Field(default_factory=list, description="Main ticker OHLCV windows")
    peer_ohlcv: list[OHLCVWindowResult] = Field(default_factory=list, description="Peer ticker 1y daily OHLCV")
    index_ohlcv: list[OHLCVWindowResult] = Field(default_factory=list, description="Ticker benchmark index(es) 1y daily OHLCV")
    macro: list[MacroResult] = Field(default_factory=list, description="Macro commodity/rate results")
    bond: Optional[BondResult] = Field(None, description="US Bond yield curve")

    def to_context_lines(self) -> list[str]:
        """Render full quant collection as context lines for LLM synthesis."""
        lines: list[str] = []
        for w in self.ohlcv_windows:
            lines.extend(w.to_context_lines())
        if self.peer_ohlcv:
            peer_str = ", ".join(r.ticker for r in self.peer_ohlcv)
            lines.append(f"\n=== Peer OHLCV ({peer_str}) — 1y daily ===")
            for r in self.peer_ohlcv:
                lines.extend(r.to_context_lines())
        for idx_ohlcv in self.index_ohlcv:
            lines.extend(idx_ohlcv.to_context_lines())
        for m in self.macro:
            lines.extend(m.to_context_lines())
        if self.bond:
            lines.extend(self.bond.to_context_lines())
        return lines
