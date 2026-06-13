"""backend.auth -- authentication domain package.

Manages authentication concerns:

* :mod:`~backend.auth.jwt`    -- HS256 JWT encoding + Centrifugo token generation.
* :mod:`~backend.auth.guest`  -- guest user creation and bearer-token validation.
* :mod:`~backend.auth.schemas` -- Pydantic response models for auth endpoints.
* :mod:`~backend.auth.errors` -- error code constants.

The FastAPI router lives in :mod:`backend.api.auth.router`.
"""

from __future__ import annotations

from backend.auth.guest import ensure_guest
from backend.auth.jwt import make_connection_token, make_subscription_token

__all__ = [
    "ensure_guest",
    "make_connection_token",
    "make_subscription_token",
]
