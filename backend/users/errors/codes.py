"""Users / auth layer error code registry.

Error code prefixes
-------------------
``USERS_``   — User management and authentication failures.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Error code constants
# ---------------------------------------------------------------------------

#: Failed to create a guest user after the maximum number of DB retry attempts.
USERS_GUEST_CREATE_FAILED = "USERS_GUEST_CREATE_FAILED"

# ---------------------------------------------------------------------------
# Description registry
# ---------------------------------------------------------------------------

#: Maps each users error code to a human-readable description.
USERS_ERRORS: dict[str, str] = {
    USERS_GUEST_CREATE_FAILED: (
        "Failed to create a guest user account after multiple attempts. "
        "Check the database connectivity and the fin_users.users table constraints."
    ),
}
