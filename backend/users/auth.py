"""users.auth — shim re-exporting from backend.auth.guest.

Guest user management has moved to :mod:`backend.auth.guest`.
This module is kept for backward-compatible imports.
"""

from backend.auth.guest import ensure_guest

__all__ = ["ensure_guest"]
