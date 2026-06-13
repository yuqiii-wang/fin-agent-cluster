"""centrifugo.tokens -- shim re-exporting from backend.auth.jwt.

JWT generation for Centrifugo has moved to :mod:`backend.auth.jwt`.
This module is kept for backward-compatible imports.
"""

from backend.auth.jwt import make_connection_token, make_subscription_token

__all__ = ["make_connection_token", "make_subscription_token"]
