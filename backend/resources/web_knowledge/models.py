"""Pydantic models for the web-knowledge sub-API."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class WebPageType(str, Enum):
    """Supported page types for web-knowledge fetches."""

    competitors = "competitors"
    press_releases = "press_releases"
    option_chain = "option_chain"


class WebPageResponse(BaseModel):
    """Fetched web page result."""

    symbol: str = Field(..., description="Equity symbol, e.g. 'AAPL'.")
    exchange: str | None = Field(default=None, description="Exchange the symbol is listed on, e.g. 'NASDAQ'.")
    page_type: WebPageType = Field(..., description="The category of web page that was fetched.")
    url: str = Field(..., description="Canonical URL that was fetched.")
    html: str = Field(..., description="Raw HTML content of the fetched page.")
