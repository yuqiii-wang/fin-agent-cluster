"""Celery beat worker — persist LLM completion records to PostgreSQL.

Reads ``fin:llm:completions`` (consumer group ``pg-persist``) on a schedule,
INSERTs each record into ``fin_agents.llm_responses``, then XACKs and XDELs.

Delete contract
---------------
A Redis message is removed only **after** it has been successfully persisted:

  1. ``xread_group`` — claim the message.
  2. ``_upsert_response`` — INSERT to PostgreSQL (idempotent, ON CONFLICT DO NOTHING).
  3. ``xack`` — remove from the consumer group's pending-entry list.
  4. ``xdel`` — remove the entry from the stream itself.

The task is scheduled via Celery beat (``PG_PERSIST.beat_interval`` seconds).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.streaming.celery_app import celery_app
from backend.streaming.config import PG_PERSIST
from backend.streaming.errors import STREAM_WORKER_BATCH_FAILED, STREAM_WORKER_MSG_FAILED
from backend.streaming.schemas import LLMCompletionMessage
from backend.streaming.streams import ensure_group, xack, xdel, xread_group

logger = logging.getLogger(__name__)

_STREAM = PG_PERSIST.stream_key
_GROUP = PG_PERSIST.consumer_group
_CONSUMER = PG_PERSIST.consumer_name
_BATCH = PG_PERSIST.batch_size


@celery_app.task(
    name="backend.streaming.workers.pg_persist.persist_llm_completions",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def persist_llm_completions(self: Any) -> dict[str, int]:
    """Celery beat task: read ``fin:llm:completions`` and persist to PostgreSQL.

    Reads pending messages first (re-delivery after crash), then new messages.
    Each record is inserted with ``ON CONFLICT (event_id) DO NOTHING`` for
    idempotent re-delivery safety.

    Returns:
        Stats dict ``{"processed": int, "persisted": int, "acked": int}``.
    """
    try:
        return asyncio.run(_persist_batch())
    except Exception as exc:
        logger.warning("[%s] persist_llm_completions failed: %s", STREAM_WORKER_BATCH_FAILED, exc)
        raise self.retry(exc=exc)


async def _persist_batch() -> dict[str, int]:
    """Read one batch from ``fin:llm:completions`` and persist to DB.

    Returns:
        Stats dict ``{"processed": int, "persisted": int, "acked": int}``.
    """
    await ensure_group(_STREAM, _GROUP)

    # Re-deliver pending messages (unacked from previous run) before new ones.
    pending = await xread_group(
        _STREAM,
        _GROUP,
        _CONSUMER,
        count=_BATCH,
        block_ms=0,
        pending=True,
    )
    messages = pending or await xread_group(
        _STREAM,
        _GROUP,
        _CONSUMER,
        count=_BATCH,
        block_ms=200,
    )

    if not messages:
        return {"processed": 0, "persisted": 0, "acked": 0}

    processed = persisted = acked = 0
    for msg_id, fields in messages:
        try:
            record = LLMCompletionMessage.model_validate(fields)
            await _upsert_response(record)
            await xack(_STREAM, _GROUP, msg_id)
            await xdel(_STREAM, msg_id)
            persisted += 1
            acked += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "[%s] persist failed msg_id=%s: %s",
                STREAM_WORKER_MSG_FAILED, msg_id, exc,
            )
        processed += 1

    if persisted:
        logger.debug("[pg_persist] persisted=%d acked=%d", persisted, acked)
    return {"processed": processed, "persisted": persisted, "acked": acked}


async def _upsert_response(record: LLMCompletionMessage) -> None:
    """INSERT one LLM completion record to ``fin_agents.llm_responses``.

    Uses ``ON CONFLICT (event_id) DO NOTHING`` for idempotent re-delivery.
    ``task_id`` is persisted when present, establishing the optional 1:1 link
    between ``llm_responses`` and ``tasks``.

    Args:
        record: Validated :class:`~backend.streaming.schemas.LLMCompletionMessage`.
    """
    from backend.db import raw_conn  # noqa: PLC0415

    async with raw_conn() as conn:
        cur = await conn.execute(
            """
            INSERT INTO fin_agents.llm_responses
                (event_id, ts, thread_id, task_id, provider, model, task_name, node_name,
                 prompt_tokens, prompts, thinking, answer,
                 completion_tokens, total_tokens, latency_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
            RETURNING id
            """,
            (
                record.event_id,
                record.ts,
                record.thread_id,
                record.task_id,
                record.provider,
                record.model,
                record.task_name,
                record.node_name,
                record.prompt_tokens,
                record.prompts,
                record.thinking,
                record.answer,
                record.completion_tokens,
                record.total_tokens,
                record.latency_ms,
            ),
        )
        row = await cur.fetchone()
        if row is None:
            cur2 = await conn.execute(
                "SELECT thread_id FROM fin_agents.llm_responses WHERE event_id = %s",
                (record.event_id,),
            )
            existing = await cur2.fetchone()
            existing_thread = existing["thread_id"] if existing else "unknown"
            logger.debug(
                "[pg_persist] duplicate event_id=%s existing_thread=%s incoming_thread=%s",
                record.event_id, existing_thread, record.thread_id,
            )
