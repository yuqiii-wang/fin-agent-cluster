"""ToolInfo -- lightweight metadata model bridging NodeTask and agent tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ToolInfo(BaseModel):
    """Serialisable metadata for a single agent tool (NodeTask).

    NodeTask carries the full implementation (Pydantic schema, coroutine,
    Celery dispatch).  ToolInfo is the lightweight, read-only projection used
    for capability selection and system-prompt context building.

    Attributes:
        name:         Unique tool name (matches NodeTask.name / StructuredTool.name).
        description:  Human-readable description forwarded to the LLM.
        input_schema: JSON Schema dict generated from the NodeTask input_type model.
    """

    name: str
    description: str
    input_schema: dict[str, Any]

    model_config = {"frozen": True}
