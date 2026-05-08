"""base — abstract base Pydantic models for node and task I/O.

Every concrete node/task input and output model must inherit from the
corresponding base class defined here.  The base classes enforce the
minimum required fields so all payloads stored in ``node_executions``
and ``fin_agents.tasks`` share a consistent structure.

Node I/O
--------
``NodeBaseInput``  — written to ``node_executions.input``.
``NodeBaseOutput`` — written to ``node_executions.output``.

Task I/O
--------
``TaskBaseInput``  — written to ``fin_agents.tasks.input``.
``TaskBaseOutput`` — written to ``fin_agents.tasks.output``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NodeBaseInput(BaseModel):
    """Minimum required fields for every node input payload.

    Attributes:
        thread_id: LangGraph thread UUID that owns this node execution.
        node_id:   Governance UUID for this node invocation (links PG row to
                   Redis registry for cancel / status scoping).
        input:     Node-specific input data.  Subclasses may replace this with
                   a typed ``dict`` sub-model or individual typed fields.
        metadata:  Arbitrary key-value pairs for tracing and debugging.
                   Defaults to an empty dict.
    """

    thread_id: str
    node_id: str
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class NodeBaseOutput(BaseModel):
    """Minimum required fields for every node output payload.

    Attributes:
        node_execution_id: DB PK of the ``node_executions`` row for this run.
        node_id:           Governance UUID mirrored from the corresponding
                           ``NodeBaseInput`` for correlation.
        output:            Node-specific output data.  Subclasses may replace
                           this with a typed sub-model or individual fields.
        elapsed_ms:        Wall-clock duration of the node in milliseconds.
        metadata:          Arbitrary key-value pairs for tracing and debugging.
    """

    node_execution_id: int
    node_id: str
    output: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: int
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskBaseInput(BaseModel):
    """Minimum required fields for every task input payload.

    Attributes:
        thread_id: LangGraph thread UUID that owns this task.
        node_id:   Governance UUID of the parent node that dispatched this task.
        task_id:   UUID of this task invocation (PK in ``fin_agents.tasks``).
        input:     Task-specific input data.  Subclasses may replace this with
                   a typed sub-model or individual typed fields.
        metadata:  Arbitrary key-value pairs for tracing and debugging.
    """

    thread_id: str
    node_id: str
    task_id: str
    input: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskBaseOutput(BaseModel):
    """Minimum required fields for every task output payload.

    Attributes:
        task_id:    UUID of the task invocation, mirrored from ``TaskBaseInput``.
        output:     Task-specific result data.  Subclasses may replace this with
                    a typed sub-model or individual typed fields.
        elapsed_ms: Wall-clock duration of the task in milliseconds.
        metadata:   Arbitrary key-value pairs for tracing and debugging.
    """

    task_id: str
    output: dict[str, Any] = Field(default_factory=dict)
    elapsed_ms: int
    metadata: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "NodeBaseInput",
    "NodeBaseOutput",
    "TaskBaseInput",
    "TaskBaseOutput",
]
