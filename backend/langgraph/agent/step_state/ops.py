"""DB CRUD for fin_agents.agent_step_state."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.db.postgres import raw_conn
from backend.langgraph.agent.step_state.models import StepStateEntry

logger = logging.getLogger(__name__)


async def upsert_step_state(
    node_id: str,
    iteration: int,
    global_state: dict[str, Any],
    step_state: dict[str, Any],
) -> None:
    """Insert or update the step-state snapshot for *(node_id, iteration)*.

    Args:
        node_id:      Agent node UUID.
        iteration:    1-based outer-loop iteration number.
        global_state: Serialised ``AgentGlobalStateBase`` subclass snapshot.
        step_state:   Serialised per-iteration step-state (pass ``{}`` when ``None``).
    """
    async with raw_conn() as conn:
        await conn.execute(
            """
            INSERT INTO fin_agents.agent_step_state
                (node_id, iteration, global_state, step_state, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (node_id, iteration)
            DO UPDATE SET
                global_state = EXCLUDED.global_state,
                step_state   = EXCLUDED.step_state,
                updated_at   = EXCLUDED.updated_at
            """,
            (node_id, iteration, json.dumps(global_state), json.dumps(step_state)),
        )


async def get_step_states(node_id: str) -> list[StepStateEntry]:
    """Return all step-state snapshots for *node_id* ordered by iteration.

    Args:
        node_id: Agent node UUID.

    Returns:
        List of :class:`StepStateEntry` instances, oldest iteration first.
    """
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(
            """
            SELECT node_id, iteration, global_state, step_state, updated_at
            FROM fin_agents.agent_step_state
            WHERE node_id = %s
            ORDER BY iteration ASC
            """,
            (node_id,),
        )
        rows = await cur.fetchall()
    return [
        StepStateEntry(
            node_id=row["node_id"],
            iteration=row["iteration"],
            global_state=row["global_state"] if isinstance(row["global_state"], dict) else json.loads(row["global_state"]),
            step_state=row["step_state"] if isinstance(row["step_state"], dict) else json.loads(row["step_state"]),
            updated_at=row["updated_at"],
        )
        for row in rows
    ]


__all__ = ["get_step_states", "upsert_step_state"]
