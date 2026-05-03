"""auth.jwt — HS256 JWT encoding and Centrifugo token generation.

Centrifugo v6 authenticates WebSocket connections and channel subscriptions
via HS256-signed JWTs.  This module generates both token types using Python's
built-in ``hmac`` + ``hashlib`` modules (no external JWT library required).

Token types
-----------
**Connection token** — authenticates the WebSocket connection itself.
  Claims: ``sub`` (user_id), ``iat``, ``exp``.

**Subscription token** — authorises a client to subscribe to one channel.
  Claims: ``sub`` (user_id), ``channel``, ``iat``, ``exp``.

Channel naming
--------------
Thread lifecycle events travel on ``thread:{thread_id}`` (``thread`` namespace).
Per-task token streams travel on ``stream:{task_id}`` (``stream`` namespace).
A task has a 1:1 mapping to a stream — ``stream_id == task_id``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time


def _b64url(data: bytes) -> str:
    """URL-safe base64 encode *data* with no padding.

    Args:
        data: Raw bytes to encode.

    Returns:
        URL-safe base64 string without ``=`` padding.
    """
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _encode_jwt(payload: dict, secret: str) -> str:
    """Encode a minimal HS256 JWT.

    Args:
        payload: JWT claims dict.
        secret:  HMAC secret key string.

    Returns:
        Compact JWT string ``header.payload.signature``.
    """
    header = _b64url(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode()
    sig = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url(sig)}"


def make_connection_token(user_id: str, secret: str, ttl_seconds: int = 3600) -> str:
    """Generate a Centrifugo WebSocket connection JWT for *user_id*.

    Args:
        user_id:     Subject claim — identifies the connecting user.
        secret:      Centrifugo ``token_hmac_secret_key``.
        ttl_seconds: Token validity window in seconds (default 1 hour).

    Returns:
        HS256-signed JWT string.
    """
    now = int(time.time())
    return _encode_jwt(
        {"sub": user_id, "iat": now, "exp": now + ttl_seconds},
        secret,
    )


def make_subscription_token(
    user_id: str,
    channel: str,
    secret: str,
    ttl_seconds: int = 3600,
) -> str:
    """Generate a Centrifugo subscription JWT for *channel*.

    Args:
        user_id:     Subject claim — identifies the subscribing user.
        channel:     Centrifugo channel name, e.g. ``thread:{thread_id}`` or
                     ``stream:{task_id}``.
        secret:      Centrifugo ``token_hmac_secret_key``.
        ttl_seconds: Token validity window (default 1 hour).

    Returns:
        HS256-signed JWT string.
    """
    now = int(time.time())
    return _encode_jwt(
        {
            "sub": user_id,
            "channel": channel,
            "iat": now,
            "exp": now + ttl_seconds,
        },
        secret,
    )


__all__ = [
    "make_connection_token",
    "make_subscription_token",
]
