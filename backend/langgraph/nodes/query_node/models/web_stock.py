"""Web-fetch intermediate models for query_node optional web-resolution tasks."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["WebStockInput", "WebStockOutput"]


class WebStockInput(BaseModel):
    """Input for ``get_stock_from_web_if_not_seen``.

    Attributes:
        stock_name: Best-guess company name or ticker from ``analyze_query``.
        query:      Original raw user query, used to widen the search context.
    """

    stock_name: str = Field(description="Best-guess company name or ticker from analyze_query.")
    query: str = Field(description="Original raw user query.")


class WebStockOutput(BaseModel):
    """Output from ``get_stock_from_web_if_not_seen``.

    Attributes:
        url:     Canonical URL of the fetched page (empty when nothing found).
        title:   Page or article title (empty when nothing found).
        content: Plain-text extract of the page (capped to 2 000 chars).
    """

    url: str = Field(default="", description="Canonical URL of the fetched page.")
    title: str = Field(default="", description="Page title.")
    content: str = Field(default="", description="Plain-text extract of the page (<=2 000 chars).")
