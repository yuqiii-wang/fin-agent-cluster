"""backend.api.centrifugo_proxy — Internal endpoint for Centrifugo RPC proxy.

Receives RPC calls forwarded by Centrifugo when a frontend client calls
``centrifuge.rpc("thread_ack", data)``.  Validates the Centrifugo proxy key,
extracts ``thread_id`` from the channel name, and dispatches to the
:mod:`backend.centrifugo_mq.rpc_proxy` handler.

Ack scopes: ``thread``, ``node``, ``task`` (carry ``ack_key``), ``stream``
(batch tracking).

This endpoint is internal-only: it is reached via Kong from the Centrifugo
containers on the Docker network, never directly by browsers.
"""

from backend.api.centrifugo_proxy.router import router

__all__ = ["router"]
