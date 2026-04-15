"""Intermediate model for the raw LLM JSON output from the query_optimizer chain.

Validates the flat dict produced by the LLM before the DB-resolution step
splits it into :class:`QuantContext` / :class:`NewsContext`.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LLMRawContext(BaseModel):
    """Flat Pydantic model for the raw LLM JSON output.

    Uses ``extra="ignore"`` so any unexpected LLM keys are silently dropped.
    Only the ticker is validated/normalised at this stage; peer counts and
    non-empty constraints are enforced later when building :class:`QuantContext`.
    """

    model_config = ConfigDict(extra="ignore")

    # ── Core identity ─────────────────────────────────────────────────────────
    ticker: str = Field(..., description="Primary ticker symbol, e.g. 'AAPL'")
    security_name: str = Field("", description="Full company or security name")
    industry: str = Field("", description="Primary industry sector")
    opposite_industry: str = Field("", description="Contrasting or competing sector")
    major_peers: list[str] = Field(default_factory=list, description="3-5 competing tickers")
    peer_tickers: list[str] = Field(default_factory=list, description="2 tickers for deep analysis")
    region: str = Field("", description="Resolved fin_markets.regions code, e.g. 'us', 'jp', 'gb'. Set to name by LLM, corrected to code by validate_basics.")
    currency_code: str = Field("", description="ISO 4217 currency code derived from the resolved region, e.g. 'USD', 'JPY'. Populated by validate_basics.")
    ticker_indexes: list[str] = Field(default_factory=list, description="List of major stock index labels from LLM, e.g. ['S&P 500', 'NASDAQ 100']")

    @field_validator("ticker", mode="before")
    @classmethod
    def ticker_must_be_nonempty_and_upper(cls, v: str) -> str:
        """Normalise ticker to uppercase and reject empty values."""
        v = str(v).strip().upper()
        if not v:
            raise ValueError("ticker must not be empty")
        return v
