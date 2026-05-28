"""Pydantic model for a single agent step-state snapshot row."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class StepStateEntry(BaseModel):
    """One row from ``fin_agents.agent_step_state``.

    Attributes:
        node_id:      Agent node UUID.
        iteration:    1-based outer-loop iteration number.
        global_state: Serialized ``AgentGlobalStateBase`` subclass snapshot.
        step_state:   Serialized per-iteration step-state snapshot (empty dict when ``None``).
        updated_at:   Timestamp of the last upsert for this row.
    """

    node_id: str
    iteration: int
    global_state: dict[str, Any]
    step_state: dict[str, Any]
    updated_at: datetime

    model_config = {"frozen": True}


__all__ = ["StepStateEntry"]
