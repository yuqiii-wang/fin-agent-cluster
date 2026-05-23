"""Pydantic models for the stats sub-API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class StatsMatrix(BaseModel):
    """Time-series matrix where the x-axis is timestamps and y-axis categories are series.

    Example::

        {
            "timestamps": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "series": {
                "close":  [182.5, 185.0, 183.2],
                "open":   [181.0, 183.5, 185.1],
                "high":   [186.0, 187.2, 186.0],
                "low":    [180.5, 182.1, 181.8],
                "volume": [72000000, 68000000, 75000000],
            }
        }
    """

    timestamps: list[str] = Field(
        ..., description="ISO-8601 date or datetime strings forming the x-axis."
    )
    series: dict[str, list[float]] = Field(
        ...,
        description=(
            "Named data series (y-axis categories). "
            "Each list must have the same length as ``timestamps``."
        ),
    )


class StatsRecord(BaseModel):
    """A statistics record for a single symbol and period."""

    id: str = Field(..., description="Unique record identifier.")
    symbol: str = Field(..., description="Equity symbol, e.g. 'AAPL'.")
    period: str = Field(..., description="Aggregation period, e.g. '1d', '1w', '1mo'.")
    content: StatsMatrix = Field(..., description="Time-series matrix payload.")
    yf_exchange: str | None = Field(None, description="yfinance exchange code, e.g. 'NMS', 'HKG'.")
    currency: str | None = Field(None, description="ISO 4217 currency code from yfinance, e.g. 'USD', 'HKD'.")


class StatsListResponse(BaseModel):
    """Paginated list of stats records."""

    items: list[StatsRecord]
    total: int = Field(..., description="Total number of matching records.")
