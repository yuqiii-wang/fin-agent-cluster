"""backend.db.redis.streams.reader -- Recovery reader for ``fin:llm:tokens`` stream entries.

After the streaming Celery task completes, this module reads every Redis Stream
entry that belongs to a given ``task_id``, reconstructs the full text fields by
ordering on the embedded ``seq`` counter, persists them to
``fin_agents.llm_responses``, and removes the consumed entries from the stream.

PostgreSQL TEXT capacity
------------------------
PostgreSQL's ``TEXT`` type has **no declared length limit**.  Values larger than
~2 kB are transparently stored via TOAST, with a practical per-value ceiling of
approximately 1 GB.  Even the longest LLM response is well within this bound, so
no truncation or chunking is needed.

Stream entry format
-------------------
Each Redis Stream entry carries a single field ``payload`` whose value is a
JSON-encoded Centrifugo publish envelope::

    {
        "method": "publish",
        "payload": "{\"channel\":\"thread:<id>\",\"data\":{
            \"event\": \"token\",
            \"thread_id\": \"...\",
            \"task_id\": \"...\",
            \"task_name\": \"...\",
            \"node_name\": \"...\",
            \"token\": \"...\",
            \"seq\": 42
        }}"
    }

Event types -> ``llm_responses`` columns
-----------------------------------------
``event="token"``          -> ``answer``
``event="thinking_token"`` -> ``thinking``
``event="prompt_token"``   -> ``prompts``

All other event types (e.g. ``stream_end``) are collected for deletion but their
content is not included in the reconstructed text.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_STREAM_NAME = "fin:llm:tokens"
_PAGE_SIZE: int = 1_000  # entries per XRANGE page

# Streaming event types that carry token text, mapped to llm_responses columns.
_TOKEN_EVENTS: dict[str, str] = {
    "token": "answer",
    "thinking_token": "thinking",
    "prompt_token": "prompts",
}


def _shard_index(thread_id: str) -> int:
    """Deterministic Redis shard index for *thread_id*.

    Mirrors the SHA-256 modulo routing used by the publisher and by Centrifugo
    token-stream nodes.

    Args:
        thread_id: LangGraph thread UUID.

    Returns:
        Zero-based shard index.
    """
    from backend.config import get_settings

    n = len(get_settings().DATABASE_REDIS_NODES) or 1
    return int(hashlib.sha256(thread_id.encode()).hexdigest(), 16) % n


async def recover_task_tokens(
    thread_id: str,
    task_id: str,
) -> tuple[dict[str, str], list[str]]:
    """Read all stream entries for *task_id* and reconstruct text in seq order.

    Scans the ``fin:llm:tokens`` stream on the shard that owns *thread_id*
    (paginated to avoid blocking), collects every entry whose ``data.task_id``
    matches, then rebuilds each text field by sorting tokens on ``data.seq``.

    Entry IDs for **all** matched entries (including ``stream_end`` and other
    non-text events) are returned so the caller can delete them in bulk.

    Args:
        thread_id: LangGraph thread UUID -- determines the Redis shard.
        task_id:   Task UUID to filter entries.

    Returns:
        A two-tuple ``(text_by_column, entry_ids)`` where:

        * ``text_by_column`` maps ``llm_responses`` column names to the
          reconstructed text (e.g. ``{"answer": "...", "thinking": "..."}``;
          keys with no content are omitted).
        * ``entry_ids`` is the list of all Redis Stream entry IDs that belong
          to *task_id*, suitable for passing to :func:`delete_stream_entries`.
    """
    from backend.db.redis import get_client

    shard = _shard_index(thread_id)
    client = await get_client(shard)

    # {event_type: {seq: token_text}} -- accumulates tokens per column.
    buckets: dict[str, dict[int, str]] = {}
    # ALL entry IDs matching task_id (token events + stream_end + any other).
    entry_ids: list[str] = []

    cursor = "-"
    while True:
        entries: list[tuple[str, dict[str, str]]] = await client.xrange(
            _STREAM_NAME, min=cursor, max="+", count=_PAGE_SIZE
        )
        if not entries:
            break

        for entry_id, fields in entries:
            raw_payload = fields.get("payload", "")
            if not raw_payload:
                continue
            try:
                outer = json.loads(raw_payload)
                data: dict[str, Any] = outer.get("data", {})
            except (json.JSONDecodeError, AttributeError):
                continue

            if data.get("task_id") != task_id:
                continue

            # Collect ALL matching entries for deletion (including stream_end).
            entry_ids.append(entry_id)

            event = data.get("event", "")
            if event not in _TOKEN_EVENTS:
                # stream_end, or unknown event -- counted for deletion only.
                continue

            token: str = data.get("token", "")
            seq: int | None = data.get("seq")
            if not token or seq is None:
                continue

            buckets.setdefault(event, {})[int(seq)] = token

        if len(entries) < _PAGE_SIZE:
            break
        # Exclusive lower bound for next page.
        cursor = f"({entries[-1][0]}"

    # Reconstruct each text field by sorting on seq.
    text_by_column: dict[str, str] = {}
    for event_type, seq_map in buckets.items():
        column = _TOKEN_EVENTS[event_type]
        text = "".join(seq_map[s] for s in sorted(seq_map))
        if text:
            text_by_column[column] = text

    logger.debug(
        "[recover_task_tokens] thread_id=%s task_id=%s matched_entries=%d columns=%s",
        thread_id,
        task_id,
        len(entry_ids),
        list(text_by_column.keys()),
    )
    return text_by_column, entry_ids


async def delete_stream_entries(thread_id: str, entry_ids: list[str]) -> int:
    """Delete *entry_ids* from the Redis Stream shard for *thread_id*.

    Uses a single ``XDEL`` call to remove all entries in one round-trip.
    Entries that no longer exist (e.g. already trimmed by MAXLEN) are silently
    ignored by Redis.

    Args:
        thread_id:  LangGraph thread UUID -- determines the Redis shard.
        entry_ids:  Stream entry IDs returned by :func:`recover_task_tokens`.

    Returns:
        Number of entries actually deleted by Redis.
    """
    if not entry_ids:
        return 0

    from backend.db.redis import get_client

    shard = _shard_index(thread_id)
    client = await get_client(shard)

    deleted: int = await client.xdel(_STREAM_NAME, *entry_ids)
    logger.debug(
        "[delete_stream_entries] thread_id=%s deleted=%d/%d",
        thread_id,
        deleted,
        len(entry_ids),
    )
    return deleted


__all__ = ["recover_task_tokens", "delete_stream_entries"]
