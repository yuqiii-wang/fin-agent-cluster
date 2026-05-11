"""FastAPI router — internal Centrifugo RPC proxy endpoint.

Receives RPC proxy requests forwarded by Centrifugo when the frontend calls
``centrifuge.rpc("thread_ack", data)`` on the SSE WebSocket connection.

Security
--------
The endpoint validates ``X-Centrifugo-Proxy-Key`` against
``settings.CENTRIFUGO_RPC_PROXY_KEY``.  Only Centrifugo containers (on the
internal Docker network) should reach this path; browsers never call it
directly.

Centrifugo RPC proxy request format (v6)
-----------------------------------------
.. code-block:: json

    {
        "client": "<client-id>",
        "transport": "websocket",
        "protocol": "json",
        "encoding": "json",
        "method": "thread_ack",
        "data": {
            "scope": "task",
            "ack_key": "task:<uuid>:completed",
            "thread_id": "<thread-uuid>"
        }
    }

Response (success)
------------------
.. code-block:: json

    {"result": {}}

Ack scopes
----------
  ``thread`` — thread-level events (done, query_status, …).
               Payload: ``{scope, ack_key, thread_id}``
  ``node``   — node execution events (node_status, node_input, …).
               Payload: ``{scope, ack_key, thread_id}``
  ``task``   — task lifecycle events (started / completed / failed / cancelled).
               Payload: ``{scope, ack_key, thread_id}``
  ``stream`` — token-batch delivery tracking (emits stream_complete when done).
               Payload: ``{scope, stream_id, event_type, thread_id}``

The ``ack_key`` must match the ``dedup_key`` used in the corresponding
``notify()`` call on the backend (e.g. ``"task:<uuid>:completed"``).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from backend.centrifugo_mq.rpc_proxy import handle_ack_rpc
from backend.config import get_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/centrifugo", tags=["centrifugo-internal"])


class _RpcProxyRequest(BaseModel):
    """Centrifugo v6 RPC proxy request envelope."""

    client: str = ""
    transport: str = ""
    protocol: str = ""
    encoding: str = ""
    method: str = ""
    data: dict[str, Any] = {}


class _RpcProxyResponse(BaseModel):
    """Centrifugo v6 RPC proxy response envelope."""

    result: dict[str, Any] = {}


@router.post("/rpc", response_model=_RpcProxyResponse, status_code=200)
async def centrifugo_rpc_proxy(
    body: _RpcProxyRequest,
    x_centrifugo_proxy_key: str = Header(default=""),
) -> _RpcProxyResponse:
    """Receive a Centrifugo RPC proxy call and dispatch to the ack handler.

    Called by Centrifugo (not browsers) when the frontend invokes
    ``centrifuge.rpc("thread_ack", data)`` on the SSE WebSocket.

    Args:
        body:                   Centrifugo RPC proxy request envelope.
        x_centrifugo_proxy_key: Proxy authentication key from the
                                ``X-Centrifugo-Proxy-Key`` header.

    Returns:
        Empty ``{"result": {}}`` on success.

    Raises:
        HTTPException(401): If the proxy key is invalid.
        HTTPException(400): If the ack payload is malformed.
    """
    settings = get_settings()
    if x_centrifugo_proxy_key != settings.CENTRIFUGO_RPC_PROXY_KEY:
        logger.error("[centrifugo_rpc_proxy] invalid proxy key method=%s", body.method)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid proxy key")

    if body.method != "thread_ack":
        logger.warning("[centrifugo_rpc_proxy] unknown rpc method=%s", body.method)
        return _RpcProxyResponse()

    data = body.data
    thread_id: str = data.get("thread_id", "")
    scope: str = data.get("scope", "")

    if not thread_id or not scope:
        logger.error(
            "[centrifugo_rpc_proxy] missing thread_id or scope method=%s data=%s",
            body.method,
            data,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing thread_id or scope in RPC data",
        )

    await handle_ack_rpc(thread_id, scope, data)
    return _RpcProxyResponse()
