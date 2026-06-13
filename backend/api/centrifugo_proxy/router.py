"""FastAPI router -- internal Centrifugo publish-proxy endpoint.

Receives publish-proxy requests forwarded by Centrifugo when a subscribed
frontend client calls ``sub.publish(data)`` on a ``thread:{thread_id}``
channel that has ``publish_proxy_enabled: true`` configured.

Security
--------
The endpoint validates ``X-Centrifugo-Proxy-Key`` against
``settings.CENTRIFUGO_RPC_PROXY_KEY``.  Only Centrifugo containers (on the
internal Docker network) should reach this path; browsers never call it
directly.

Centrifugo publish proxy request format (v6)
---------------------------------------------
.. code-block:: json

    {
        "client": "<client-id>",
        "transport": "websocket",
        "protocol": "json",
        "encoding": "json",
        "channel": "thread:<thread-uuid>",
        "data": {
            "event": "ack",
            "scope": "task",
            "ack_key": "task:<uuid>:completed:<nonce>",
            "thread_id": "<thread-uuid>"
        },
        "user": "<user-id>"
    }

Response (success)
------------------
.. code-block:: json

    {"result": {"skip_history": true}}

``skip_history: true`` prevents ACK publications from being stored in
Centrifugo channel history and replayed to reconnecting clients.

ACK flow
--------
1. Backend ``notify()`` publishes an SSE event with a nonce-stamped ``ack_key``
   and blocks on ``BLPOP session:notify_ack:{thread_id}:{ack_key}``.
2. Frontend receives the event via ``sub.on('publication', ...)``.
3. Frontend calls ``sub.publish({event: "ack", ack_key: ..., ...})``.
4. Centrifugo intercepts the publish (publish proxy) and POSTs here.
5. This endpoint calls ``signal_notify_ack`` -> Redis LPUSH unblocks the waiter.
6. FastAPI returns ``{"result": {"skip_history": true}}``.
7. Centrifugo resolves the frontend ``sub.publish()`` promise.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from backend.centrifugo_mq.publish_proxy import handle_ack_publish
from backend.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/centrifugo", tags=["centrifugo-internal"])


class _PublishProxyRequest(BaseModel):
    """Centrifugo v6 publish proxy request envelope."""

    client: str = ""
    transport: str = ""
    protocol: str = ""
    encoding: str = ""
    channel: str = ""
    data: dict[str, Any] = {}
    user: str = ""


class _PublishProxyResult(BaseModel):
    """Inner ``result`` for the publish proxy response."""

    skip_history: bool = True


class _PublishProxyResponse(BaseModel):
    """Centrifugo v6 publish proxy response envelope."""

    result: _PublishProxyResult = _PublishProxyResult()


@router.post("/publish", response_model=_PublishProxyResponse, status_code=200)
async def centrifugo_publish_proxy(
    body: _PublishProxyRequest,
    x_centrifugo_proxy_key: str = Header(default=""),
) -> _PublishProxyResponse:
    """Receive a Centrifugo publish proxy call and dispatch to the ACK handler.

    Called by Centrifugo (not browsers) when a frontend client calls
    ``sub.publish(data)`` on the ``thread:{thread_id}`` SSE channel.

    Args:
        body:                   Centrifugo publish proxy request envelope.
        x_centrifugo_proxy_key: Proxy authentication key from the
                                ``X-Centrifugo-Proxy-Key`` header.

    Returns:
        ``{"result": {"skip_history": true}}`` on success.

    Raises:
        HTTPException(401): If the proxy key is invalid.
    """
    settings = get_settings()
    if x_centrifugo_proxy_key != settings.CENTRIFUGO_RPC_PROXY_KEY:
        logger.error("[centrifugo_publish_proxy] invalid proxy key channel=%s", body.channel)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid proxy key")

    channel = body.channel
    if not channel.startswith("thread:"):
        logger.warning("[centrifugo_publish_proxy] unexpected channel=%s", channel)
        return _PublishProxyResponse()

    thread_id = channel.removeprefix("thread:")
    event: str = body.data.get("event", "")

    if event != "ack":
        logger.warning(
            "[centrifugo_publish_proxy] unsupported event=%s thread_id=%s", event, thread_id
        )
        return _PublishProxyResponse()

    await handle_ack_publish(thread_id, body.data)
    return _PublishProxyResponse()
