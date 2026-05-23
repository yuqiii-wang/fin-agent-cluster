"""DB CRUD for fin_agents.agent_memory."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.db.postgres import raw_conn
from backend.langgraph.agent.memory.models import MemoryEntry

logger = logging.getLogger(__name__)


async def append_memory_entry(
    thread_id: str,
    node_id: str,
    entry_type: str,
    content: dict[str, Any],
    seq_num: int,
) -> str:
    """Insert a new chronological memory entry and return its ``memory_id``.

    Args:
        thread_id:  LangGraph thread UUID.
        node_id:    Agent node UUID.
        entry_type: One of the ``entry_type`` CHECK values.
        content:    Arbitrary JSON payload for the entry.
        seq_num:    Monotonic sequence number within this node execution.

    Returns:
        The generated ``memory_id`` UUID string.
    """
    async with raw_conn() as conn:
        cur = await conn.execute(
            """
            INSERT INTO fin_agents.agent_memory
                (thread_id, node_id, entry_type, content, seq_num)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING memory_id
            """,
            (thread_id, node_id, entry_type, json.dumps(content), seq_num),
        )
        row = await cur.fetchone()
    return str(row["memory_id"])


async def get_max_seq_num(node_id: str) -> int:
    """Return the current maximum ``seq_num`` for *node_id*, or 0 if none.

    Args:
        node_id: Agent node UUID.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            "SELECT COALESCE(MAX(seq_num), 0) AS max_seq"
            " FROM fin_agents.agent_memory WHERE node_id = %s",
            (node_id,),
        )
        row = await cur.fetchone()
    return int(row["max_seq"]) if row else 0


async def get_memory_entries(
    node_id: str,
    *,
    include_forgotten: bool = False,
    include_compacted: bool = False,
) -> list[MemoryEntry]:
    """Retrieve memory entries for *node_id* in chronological order.

    Args:
        node_id:           Agent node UUID.
        include_forgotten: Also return entries with status ``'forgotten'``.
        include_compacted: Also return original entries with status ``'compacted'``.

    Returns:
        List of :class:`MemoryEntry` ordered by ``(seq_num, created_at)``.
    """
    statuses: list[str] = ["active"]
    if include_forgotten:
        statuses.append("forgotten")
    if include_compacted:
        statuses.append("compacted")

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            """
            SELECT memory_id, thread_id, node_id, entry_type, content,
                   seq_num, status, compacted_into, created_at
            FROM fin_agents.agent_memory
            WHERE node_id = %s AND status = ANY(%s)
            ORDER BY seq_num, created_at
            """,
            (node_id, statuses),
        )
        rows = await cur.fetchall()

    return [
        MemoryEntry(
            memory_id=str(r["memory_id"]),
            thread_id=str(r["thread_id"]),
            node_id=str(r["node_id"]),
            entry_type=r["entry_type"],
            content=r["content"],
            seq_num=r["seq_num"],
            status=r["status"],
            compacted_into=str(r["compacted_into"]) if r["compacted_into"] else None,
            created_at=r["created_at"],
        )
        for r in rows
    ]


async def forget_memory_entry(node_id: str, memory_id: str) -> bool:
    """Mark a memory entry as forgotten.

    Only transitions entries that are currently ``'active'``; idempotent
    for already-forgotten or compacted entries.

    Args:
        node_id:   Agent node UUID (ownership check).
        memory_id: Memory entry UUID to forget.

    Returns:
        ``True`` if updated; ``False`` if not found or already non-active.
    """
    async with raw_conn() as conn:
        cur = await conn.execute(
            """
            UPDATE fin_agents.agent_memory
            SET status = 'forgotten'
            WHERE memory_id = %s AND node_id = %s AND status = 'active'
            RETURNING memory_id
            """,
            (memory_id, node_id),
        )
        row = await cur.fetchone()
    return row is not None


async def compact_memory_entries(
    thread_id: str,
    node_id: str,
    memory_ids: list[str],
    summary: str,
) -> str | None:
    """Merge selected active entries into a single ``compacted_summary`` entry.

    The new summary is inserted at the ``seq_num`` of the earliest entry in
    the group.  All source entries are marked ``'compacted'``.

    Args:
        thread_id:  LangGraph thread UUID.
        node_id:    Agent node UUID (ownership check on entries).
        memory_ids: UUIDs of active entries to compact (minimum 2 required).
        summary:    Human-readable text replacing the compacted entries.

    Returns:
        The ``memory_id`` of the new ``compacted_summary`` entry, or ``None``
        if fewer than 2 valid active entries were found.
    """
    if len(memory_ids) < 2:
        return None

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            """
            SELECT memory_id, seq_num
            FROM fin_agents.agent_memory
            WHERE memory_id = ANY(%s) AND node_id = %s AND status = 'active'
            ORDER BY seq_num
            """,
            (memory_ids, node_id),
        )
        rows = await cur.fetchall()

    if len(rows) < 2:
        return None

    active_ids = [str(r["memory_id"]) for r in rows]
    summary_seq = rows[0]["seq_num"]

    async with raw_conn() as conn:
        cur = await conn.execute(
            """
            INSERT INTO fin_agents.agent_memory
                (thread_id, node_id, entry_type, content, seq_num)
            VALUES (%s, %s, 'compacted_summary', %s, %s)
            RETURNING memory_id
            """,
            (thread_id, node_id, json.dumps({"summary": summary}), summary_seq),
        )
        row = await cur.fetchone()
        new_memory_id = str(row["memory_id"])

        await conn.execute(
            """
            UPDATE fin_agents.agent_memory
            SET status = 'compacted', compacted_into = %s
            WHERE memory_id = ANY(%s) AND node_id = %s
            """,
            (new_memory_id, active_ids, node_id),
        )

    return new_memory_id


async def compact_if_needed(
    node_id: str,
    thread_id: str,
    *,
    keep_recent: int = 6,
) -> bool:
    """Auto-compact old active entries when their count exceeds ``2 × keep_recent``.

    Mirrors Claude Code's auto-compact behaviour: preserves the most recent
    ``keep_recent`` active non-summary entries and condenses everything older
    into a single ``compacted_summary`` so the context window stays tight on
    subsequent runs.  Existing ``compacted_summary`` entries are never re-
    compacted.

    Args:
        node_id:     Agent node UUID.
        thread_id:   LangGraph thread UUID.
        keep_recent: Minimum number of most-recent entries to keep active.

    Returns:
        ``True`` if compaction was performed; ``False`` if not needed.
    """
    entries = await get_memory_entries(node_id)
    # Never compact compacted_summary entries — they are already condensed.
    compactable = [e for e in entries if e.entry_type != "compacted_summary"]

    if len(compactable) <= keep_recent * 2:
        return False

    to_compact = compactable[:-keep_recent]
    if len(to_compact) < 2:
        return False

    # Build a plain-text summary of the entries being compacted so the
    # resulting compacted_summary remains human-readable.
    summary_parts: list[str] = []
    for entry in to_compact:
        c = entry.content
        text = str(c.get("text") or c.get("summary") or c.get("result") or c)[:150]
        label = entry.entry_type.replace("_", " ")
        summary_parts.append(f"[{label}] {text}")

    await compact_memory_entries(
        thread_id,
        node_id,
        [e.memory_id for e in to_compact],
        "\n".join(summary_parts),
    )
    return True


# ===========================================================================
# Candidate search for capability selection
# ===========================================================================


def extract_memory_text(content: dict[str, Any]) -> str:
    """Extract a flat, searchable string from a memory entry content dict.

    Concatenates string and dict/list values (capped for performance) so
    keyword searches have a single text target per entry.

    Args:
        content: The ``content`` dict stored on a :class:`MemoryEntry`.

    Returns:
        Space-joined string of extracted text fragments.
    """
    parts: list[str] = []
    for v in content.values():
        if isinstance(v, str):
            parts.append(v[:300])
        elif isinstance(v, (dict, list)):
            parts.append(str(v)[:200])
    return " ".join(parts)


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    """Return ``True`` if any keyword appears in *text* (case-insensitive)."""
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def search_memory_candidates(
    memory: list[MemoryEntry],
    keywords: list[str],
    max_results: int,
) -> list[MemoryEntry]:
    """Return memory entries whose content text matches any keyword.

    Falls back to the most-recent *max_results* entries when no keyword
    match is found (ensures at least some prior context is always presented).

    Args:
        memory:      All active memory entries for the node (chronological).
        keywords:    Keywords extracted from the current task description.
        max_results: Maximum candidates to return.

    Returns:
        Filtered and capped list of :class:`MemoryEntry`.
    """
    if not keywords:
        return memory[-max_results:]
    matched = [
        e for e in memory
        if _matches_keywords(extract_memory_text(e.content), keywords)
    ]
    return (matched if matched else memory[-max_results:])[:max_results]


__all__ = [
    "append_memory_entry",
    "compact_if_needed",
    "compact_memory_entries",
    "extract_memory_text",
    "forget_memory_entry",
    "get_max_seq_num",
    "get_memory_entries",
    "search_memory_candidates",
]
