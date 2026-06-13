"""backend.users.auth -- re-exports the guest auth helper for API routers."""

from __future__ import annotations

from backend.auth.guest import ensure_guest

__all__ = ["ensure_guest"]
