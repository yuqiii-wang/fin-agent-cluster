"""Data models for backend.resources.info."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["InfoResult"]


class InfoResult(BaseModel):
    """A single web search result.

    Attributes:
        url:     Landing page URL.
        title:   Page or article title.
        content: Plain-text body snippet (truncated to a configurable limit).
    """

    url: str = Field(default="", description="Landing page URL.")
    title: str = Field(default="", description="Page or article title.")
    content: str = Field(default="", description="Plain-text body snippet.")
