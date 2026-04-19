"""Guest user creation and token validation."""

from __future__ import annotations

import random
import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from backend.db.postgres.engine import get_session_factory
from backend.users.models import GuestUser


def _utcnow() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)


def _new_username() -> str:
    """Generate a unique guest username like ``guest_482910``."""
    return f"guest_{random.randint(100_000, 999_999)}"


async def ensure_guest(token: str | None) -> tuple[GuestUser, bool]:
    """Return ``(user, is_new)``.

    If *token* matches an existing row the user's ``last_seen_at`` is updated
    and ``is_new=False`` is returned.  Otherwise a fresh guest account is
    created and ``is_new=True`` is returned.

    Args:
        token: UUID bearer token from the browser's localStorage, or ``None``
               on a first-ever visit.

    Returns:
        A ``(GuestUser, is_new)`` tuple.
    """
    factory = get_session_factory()
    async with factory() as session:
        if token:
            result = await session.execute(
                select(GuestUser).where(GuestUser.id == token)
            )
            user = result.scalar_one_or_none()
            if user:
                await session.execute(
                    update(GuestUser)
                    .where(GuestUser.id == token)
                    .values(last_seen_at=_utcnow())
                )
                await session.commit()
                return user, False

        # Create a new guest — retry on the unlikely username collision
        for _ in range(5):
            new_id = str(uuid.uuid4())
            username = _new_username()
            guest = GuestUser(id=new_id, username=username)
            try:
                session.add(guest)
                await session.commit()
                await session.refresh(guest)
                return guest, True
            except Exception:
                await session.rollback()
                continue

        raise RuntimeError("Failed to create guest user after 5 attempts")
