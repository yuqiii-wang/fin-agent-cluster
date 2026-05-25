"""Prompt builder registry for streaming Celery tasks.

Maps task_name → callable(payload: dict) -> list[BaseMessage].
Tasks that run via delegate_stream register their prompt builders here.
Populated lazily on first use to avoid circular imports at module load time.
"""

from __future__ import annotations

from typing import Any

STREAM_PROMPT_BUILDERS: dict[str, Any] = {}


def get_stream_prompt_builders() -> dict[str, Any]:
    """Lazily load and merge all registered stream prompt builders."""
    if STREAM_PROMPT_BUILDERS:
        return STREAM_PROMPT_BUILDERS
    from backend.langgraph.nodes.query_node.tasks import STREAM_PROMPT_BUILDERS as _QPB
    from backend.langgraph.nodes.prepare_peers.tasks import STREAM_PROMPT_BUILDERS as _APB
    from backend.langgraph.models.common_tasks import STREAM_PROMPT_BUILDERS as _CPB
    STREAM_PROMPT_BUILDERS.update(_QPB)
    STREAM_PROMPT_BUILDERS.update(_APB)
    STREAM_PROMPT_BUILDERS.update(_CPB)
    return STREAM_PROMPT_BUILDERS
