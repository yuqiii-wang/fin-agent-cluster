"""auth.schemas — Pydantic response models for the authentication layer."""

from __future__ import annotations

from pydantic import BaseModel


class CentrifugoTokenResponse(BaseModel):
    """Response returned by ``GET /auth/centrifugo/token``.

    Used for LLM token streaming — connects the frontend to the shard-specific
    centrifugo-token-0 or centrifugo-token-1 node backed by the matching Redis instance.
    """

    ws_url: str
    connection_token: str
    subscription_token: str
    shard_index: int
    channel: str


class CentrifugoSseTokenResponse(BaseModel):
    """Response returned by ``GET /auth/centrifugo/sse-token``.

    Used for SSE lifecycle events — connects the frontend to the correct
    centrifugo-sse-{shard} node.  Shard is determined by SHA-256(thread_id) % 2.
    """

    ws_url: str
    connection_token: str
    subscription_token: str
    shard_index: int
    channel: str


__all__ = ["CentrifugoTokenResponse", "CentrifugoSseTokenResponse"]
