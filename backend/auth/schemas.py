"""auth.schemas — Pydantic response models for the authentication layer."""

from __future__ import annotations

from pydantic import BaseModel


class CentrifugoTokenResponse(BaseModel):
    """Response returned by ``GET /auth/centrifugo/token``."""

    ws_url: str
    connection_token: str
    subscription_token: str
    shard_index: int
    channel: str


__all__ = ["CentrifugoTokenResponse"]
