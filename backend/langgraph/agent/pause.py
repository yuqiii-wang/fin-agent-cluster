"""Agent-level Redis pause, auto-resume, and state persistence flags.

Key schema
----------
fin:agent:pause:{node_id}        -- pause flag; agent loop polls before each LLM call
fin:agent:auto_resume:{node_id}  -- when set, EntrypointMixin auto-resumes after pause
fin:agent:state:{node_id}        -- reserved for future message-history persistence
"""

from __future__ import annotations

from backend.db.redis.client import get_client

_PAUSE_KEY = "fin:agent:pause:{node_id}"
_AUTO_RESUME_KEY = "fin:agent:auto_resume:{node_id}"
_STATE_KEY = "fin:agent:state:{node_id}"

_PAUSE_TTL = 3600       # 1 hour
_STATE_TTL  = 86400     # 24 hours


async def set_agent_pause_flag(node_id: str, *, auto_resume: bool = False) -> None:
    """Set the pause flag for *node_id*; optionally also set the auto-resume flag.

    Args:
        node_id:     Agent node UUID.
        auto_resume: When ``True``, also set the auto-resume flag so
                     ``EntrypointMixin`` re-dispatches the graph automatically
                     after saving context changes.
    """
    client = await get_client(shard=0)
    await client.set(_PAUSE_KEY.format(node_id=node_id), "1", ex=_PAUSE_TTL)
    if auto_resume:
        await client.set(_AUTO_RESUME_KEY.format(node_id=node_id), "1", ex=_PAUSE_TTL)


async def is_agent_pause_flag_set(node_id: str) -> bool:
    """Return ``True`` if the agent pause flag is currently set.

    Args:
        node_id: Agent node UUID.
    """
    client = await get_client(shard=0)
    return bool(await client.exists(_PAUSE_KEY.format(node_id=node_id)))


async def clear_agent_pause_flag(node_id: str) -> None:
    """Clear both the pause and auto-resume flags for *node_id*.

    Args:
        node_id: Agent node UUID.
    """
    client = await get_client(shard=0)
    await client.delete(
        _PAUSE_KEY.format(node_id=node_id),
        _AUTO_RESUME_KEY.format(node_id=node_id),
    )


async def is_agent_auto_resume_set(node_id: str) -> bool:
    """Return ``True`` if the auto-resume flag is set for *node_id*.

    Args:
        node_id: Agent node UUID.
    """
    client = await get_client(shard=0)
    return bool(await client.exists(_AUTO_RESUME_KEY.format(node_id=node_id)))


async def clear_agent_auto_resume(node_id: str) -> None:
    """Clear only the auto-resume flag, leaving the pause flag intact.

    Args:
        node_id: Agent node UUID.
    """
    client = await get_client(shard=0)
    await client.delete(_AUTO_RESUME_KEY.format(node_id=node_id))


__all__ = [
    "clear_agent_auto_resume",
    "clear_agent_pause_flag",
    "is_agent_auto_resume_set",
    "is_agent_pause_flag_set",
    "set_agent_pause_flag",
]
