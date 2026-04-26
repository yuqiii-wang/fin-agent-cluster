"""Users / auth error code registry package.

Re-exports all error code constants and the ``USERS_ERRORS`` description dict::

    from backend.users.errors import USERS_ERRORS, USERS_GUEST_CREATE_FAILED
"""

from __future__ import annotations

from backend.users.errors.codes import (
    USERS_ERRORS,
    USERS_GUEST_CREATE_FAILED,
)

__all__ = [
    "USERS_ERRORS",
    "USERS_GUEST_CREATE_FAILED",
]
