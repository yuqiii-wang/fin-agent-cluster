"""auth.errors -- error code constants for the authentication layer.

Error code prefixes
-------------------
``AUTH_``   -- Guest auth, JWT generation, and Centrifugo token failures.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

#: Failed to create a guest user after the maximum number of DB retry attempts.
AUTH_GUEST_CREATE_FAILED = "AUTH_GUEST_CREATE_FAILED"

#: User token is absent or unrecognised -- caller should create a new session.
AUTH_INVALID_TOKEN = "AUTH_INVALID_TOKEN"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each auth error code to a human-readable description.
AUTH_ERRORS: dict[str, str] = {
    AUTH_GUEST_CREATE_FAILED: (
        "Failed to create a guest user account after multiple attempts. "
        "Check the database connectivity and the fin_users.users table constraints."
    ),
    AUTH_INVALID_TOKEN: (
        "The supplied X-User-Token is missing or does not match any known user. "
        "The client should re-authenticate via POST /auth/guest."
    ),
}
