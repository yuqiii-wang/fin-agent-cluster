"""DB CRUD for fin_agents.agent_skills."""

from __future__ import annotations

import logging

from backend.db.postgres import raw_conn
from backend.langgraph.agent.skills.models import Skill

logger = logging.getLogger(__name__)


async def add_skill(
    thread_id: str,
    node_id: str,
    summary: str,
    instructions: str,
) -> Skill:
    """Insert a new active skill for *node_id* and return the created row.

    Args:
        thread_id:    LangGraph thread UUID.
        node_id:      Agent node UUID.
        summary:      One-line human-readable label for the skill.
        instructions: Full instruction text for the agent.

    Returns:
        The created :class:`Skill` instance.
    """
    async with raw_conn() as conn:
        cur = await conn.execute(
            """
            INSERT INTO fin_agents.agent_skills
                (thread_id, node_id, summary, instructions)
            VALUES (%s, %s, %s, %s)
            RETURNING skill_id, thread_id, node_id, summary, instructions,
                      status, created_at
            """,
            (thread_id, node_id, summary, instructions),
        )
        row = await cur.fetchone()

    return Skill(
        skill_id=str(row["skill_id"]),
        thread_id=str(row["thread_id"]),
        node_id=str(row["node_id"]),
        summary=row["summary"],
        instructions=row["instructions"],
        status=row["status"],
        created_at=row["created_at"],
    )


async def get_skills(node_id: str, *, active_only: bool = True) -> list[Skill]:
    """Return skills for *node_id*, ordered by creation time.

    Args:
        node_id:     Agent node UUID.
        active_only: When ``True`` (default) only return ``'active'`` skills.

    Returns:
        List of :class:`Skill` ordered by ``created_at``.
    """
    if active_only:
        where = "node_id = %s AND status = 'active'"
        params: tuple = (node_id,)
    else:
        where = "node_id = %s"
        params = (node_id,)

    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            f"""
            SELECT skill_id, thread_id, node_id, summary, instructions,
                   status, created_at
            FROM fin_agents.agent_skills
            WHERE {where}
            ORDER BY created_at
            """,
            params,
        )
        rows = await cur.fetchall()

    return [
        Skill(
            skill_id=str(r["skill_id"]),
            thread_id=str(r["thread_id"]),
            node_id=str(r["node_id"]),
            summary=r["summary"],
            instructions=r["instructions"],
            status=r["status"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


async def forget_skill(node_id: str, skill_id: str) -> bool:
    """Mark a skill as forgotten (no longer applied to future agent runs).

    Args:
        node_id:  Agent node UUID (ownership check).
        skill_id: Skill UUID to forget.

    Returns:
        ``True`` if updated; ``False`` if not found or already forgotten.
    """
    async with raw_conn() as conn:
        cur = await conn.execute(
            """
            UPDATE fin_agents.agent_skills
            SET status = 'forgotten'
            WHERE skill_id = %s AND node_id = %s AND status = 'active'
            RETURNING skill_id
            """,
            (skill_id, node_id),
        )
        row = await cur.fetchone()
    return row is not None


# ===========================================================================
# Candidate search for capability selection
# ===========================================================================


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    """Return ``True`` if any keyword appears in *text* (case-insensitive)."""
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def search_skill_candidates(
    skills: list[Skill],
    keywords: list[str],
    max_results: int,
) -> list[Skill]:
    """Return skills whose summary or instructions match any keyword.

    Falls back to the most-recent *max_results* skills when no keyword match
    is found (ensures at least some skill context is always presented).

    Args:
        skills:      All active skills for the node (ordered by creation time).
        keywords:    Keywords extracted from the current task description.
        max_results: Maximum candidates to return.

    Returns:
        Filtered and capped list of :class:`Skill`.
    """
    if not keywords:
        return skills[:max_results]
    matched = [
        s for s in skills
        if _matches_keywords(s.summary + " " + s.instructions, keywords)
    ]
    return (matched if matched else skills)[:max_results]


__all__ = [
    "add_skill",
    "forget_skill",
    "get_skills",
    "search_skill_candidates",
]
