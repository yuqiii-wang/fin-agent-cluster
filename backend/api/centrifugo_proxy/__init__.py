"""backend.api.centrifugo_proxy -- Internal endpoint for Centrifugo publish proxy.

Receives publish-proxy calls forwarded by Centrifugo when a subscribed
frontend client calls ``sub.publish(data)`` on the ``thread:{thread_id}``
channel.  Validates the Centrifugo proxy key and dispatches to
:mod:`backend.centrifugo_mq.publish_proxy`.

SSE ACK flow: client publishes ``{event: "ack", ack_key: ...}`` -> Centrifugo
publish proxy -> this endpoint -> Redis LPUSH unblocks the backend BLPOP waiter
in ``notify()``.

This endpoint is internal-only: reached via nginx-api from the Centrifugo
containers on the Docker network, never directly by browsers.
"""

from backend.api.centrifugo_proxy.router import router

__all__ = ["router"]
