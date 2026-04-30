"""FastAPI router for Centrifugo connection bootstrap.

Provides ``GET /centrifugo/token?thread_id=...`` which returns the WebSocket
URL and JWT tokens needed by the frontend centrifuge JS SDK to connect and
subscribe to the per-thread channel ``thread:{thread_id}``.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from backend.centrifugo.client import get_shard_index
from backend.centrifugo.tokens import make_connection_token, make_subscription_token
from backend.config import get_settings
from backend.users.auth import ensure_guest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/centrifugo", tags=["centrifugo"])


class CentrifugoTokenResponse(BaseModel):
    """Response returned by ``GET /centrifugo/token``."""

    ws_url: str
    connection_token: str
    subscription_token: str
    shard_index: int
    channel: str


@router.get("/token", response_model=CentrifugoTokenResponse)
async def get_centrifugo_token(
    thread_id: str,
    x_user_token: Annotated[str, Header(alias="X-User-Token")],
) -> CentrifugoTokenResponse:
    """Return Centrifugo connection and subscription tokens for *thread_id*.

    The frontend uses these tokens to establish a WebSocket connection to the
    correct Centrifugo shard and subscribe to the ``thread:{thread_id}``
    channel.

    Args:
        thread_id:     LangGraph thread UUID to subscribe to.
        x_user_token:  Guest-auth bearer token from ``localStorage``.

    Returns:
        ``CentrifugoTokenResponse`` with ``ws_url``, ``connection_token``,
        ``subscription_token``, ``shard_index``, and ``channel``.

    Raises:
        HTTPException 401: If ``x_user_token`` is invalid.
    """
    settings = get_settings()
    user, _ = await ensure_guest(x_user_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid user token")

    user_id = str(user.id)
    secret = settings.CENTRIFUGO_SECRET
    shard = get_shard_index(thread_id)
    channel = f"thread:{thread_id}"

    # Route the WebSocket URL to the correct Centrifugo shard through Kong.
    ws_url = f"{settings.CENTRIFUGO_PUBLIC_BASE}/centrifugo-{shard}/connection/websocket"

    connection_token = make_connection_token(user_id, secret)
    subscription_token = make_subscription_token(user_id, thread_id, secret)

    logger.debug(
        "[api.centrifugo] token issued user_id=%s thread_id=%s shard=%d",
        user_id,
        thread_id,
        shard,
    )
    return CentrifugoTokenResponse(
        ws_url=ws_url,
        connection_token=connection_token,
        subscription_token=subscription_token,
        shard_index=shard,
        channel=channel,
    )
