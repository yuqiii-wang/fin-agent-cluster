"""QuantContext: quant-related fields for market data collection."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuantContext(BaseModel):
    """Quant-related fields for market data collection: ticker, peers, region, futures, options."""

    model_config = ConfigDict(extra="ignore")

    ticker: str = Field(..., description="Primary ticker symbol, e.g. 'AAPL'")
    security_name: str = Field("", description="Full company or security name")
    industry: str = Field("", description="Primary industry sector")
    opposite_industry: str = Field("", description="Contrasting or competing sector")
    major_peers: list[str] = Field(
        default_factory=list,
        description="3-5 closely competing ticker symbols",
    )
    peer_tickers: list[str] = Field(
        default_factory=list,
        description="Exactly 2 tickers selected for deep comparative analysis",
    )
    region: str = Field(
        "",
        description="Resolved fin_markets.regions code, e.g. 'us', 'jp', 'gb'",
    )
    ticker_indexes: list[str] = Field(
        default_factory=list,
        description="List of market ticker symbols of indexes the ticker belongs to, e.g. ['^GSPC', '^NDX']. "
                    "Resolved from the LLM label(s) by validate_basics against fin_markets.regions.",
    )

    @field_validator("ticker", mode="before")
    @classmethod
    def ticker_must_be_nonempty_and_upper(cls, v: str) -> str:
        """Normalise ticker to uppercase and reject empty values."""
        v = str(v).strip().upper()
        if not v:
            raise ValueError("ticker must not be empty")
        return v

    @field_validator("major_peers", mode="after")
    @classmethod
    def major_peers_length(cls, v: list[str]) -> list[str]:
        """Require 3-5 entries in major_peers."""
        if not (3 <= len(v) <= 5):
            raise ValueError(f"major_peers must contain 3-5 tickers, got {len(v)}")
        return v

    @field_validator("peer_tickers", mode="after")
    @classmethod
    def peer_tickers_exactly_two(cls, v: list[str]) -> list[str]:
        """Require exactly 2 entries in peer_tickers."""
        if len(v) != 2:
            raise ValueError(f"peer_tickers must contain exactly 2 tickers, got {len(v)}")
        return v
