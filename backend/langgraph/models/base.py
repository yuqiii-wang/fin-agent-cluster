"""Base Pydantic models for the LangGraph node/task hierarchy.

Every node and task input/output should inherit from these bases so that
the thread → node → task identity chain is always present alongside the
biz-specific ``content`` payload.

Hierarchy reminder
------------------
Thread (thread_id)
  └── Node  (node_id = make_node_id(thread_id, node_name))
        └── Task  (task_id = make_task_id())

Generic usage
-------------
.. code-block:: python

    class AnalyzeQueryContent(BaseModel):
        query: str

    class AnalyzeQueryInput(BaseTaskInput[AnalyzeQueryContent]):
        pass

    inp = AnalyzeQueryInput(
        thread_id="t1",
        node_id="t1:query_node",
        task_id="uuid4",
        task_name="analyze_query",
        content=AnalyzeQueryContent(query="What is AAPL?"),
    )
"""

from __future__ import annotations

from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, Field

from backend.langgraph.lifecycle.ids import strip_node_suffix

__all__ = [
    "BaseTaskInput",
    "BaseTaskOutput",
    "BaseNodeInput",
    "BaseNodeOutput",
    "BaseThreadSseNotification",
    "BaseNodeSseNotification",
    "BaseTaskSseNotification",
]

T = TypeVar("T")


def _content_to_dict(content: Any) -> dict[str, Any]:
    """Serialize *content* to a plain dict for SSE payload spreading.

    Handles ``dict``, Pydantic ``BaseModel`` instances, and any object with a
    ``model_dump`` method.  Returns an empty dict for unsupported types so that
    callers never receive ``None`` when spreading.
    """
    if isinstance(content, dict):
        return content
    if hasattr(content, "model_dump"):
        return content.model_dump()
    return {}


class BaseTaskInput(BaseModel, Generic[T]):
    """Envelope for all @task inputs.

    Carries the full thread → node → task identity so that every handler
    has access to its location in the hierarchy without needing to accept
    the raw ``GraphState`` dict.

    Attributes:
        thread_id: LangGraph thread UUID.
        node_id: Deterministic node identifier (``{thread_id}:{node_name}``).
        task_id: Unique UUID4 for this @task invocation.
        task_name: Registered task name (e.g. ``"analyze_query"``).
        metadata: Arbitrary key/value bag for cross-cutting concerns
            (e.g. correlation IDs, feature flags, retry counts).
        content: Biz-specific input payload; type is fixed by the subclass.
    """

    thread_id: str
    node_id: str
    task_id: str
    task_name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: T


class BaseTaskOutput(BaseModel, Generic[T]):
    """Envelope for all @task outputs.

    Mirrors :class:`BaseTaskInput` so that downstream nodes/tasks can
    always identify the origin of a result.

    Attributes:
        thread_id: LangGraph thread UUID.
        node_id: Deterministic node identifier (``{thread_id}:{node_name}``).
        task_id: Unique UUID4 for this @task invocation.
        task_name: Registered task name.
        metadata: Arbitrary key/value bag propagated from the input
            and/or enriched by the handler.
        content: Biz-specific result payload; type is fixed by the subclass.
    """

    thread_id: str
    node_id: str
    task_id: str
    task_name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: T


class BaseNodeInput(BaseModel, Generic[T]):
    """Envelope for all node inputs.

    Carries the thread → node identity so that node logic always has the
    full context without reaching into raw ``GraphState`` keys.

    Attributes:
        thread_id: LangGraph thread UUID.
        node_id: Deterministic node identifier (``{thread_id}:{node_name}``).
        node_name: Registered node name (e.g. ``"query_node"``).
        metadata: Arbitrary key/value bag for cross-cutting concerns.
        content: Biz-specific input payload; type is fixed by the subclass.
    """

    thread_id: str
    node_id: str
    node_name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: T


class BaseNodeOutput(BaseModel, Generic[T]):
    """Envelope for all node outputs.

    Mirrors :class:`BaseNodeInput` so that the next node in the graph can
    always identify the origin of the state slice it is consuming.

    Attributes:
        thread_id: LangGraph thread UUID.
        node_id: Deterministic node identifier (``{thread_id}:{node_name}``).
        node_name: Registered node name.
        metadata: Arbitrary key/value bag propagated from the input
            and/or enriched by the node.
        content: Biz-specific result payload; type is fixed by the subclass.
    """

    thread_id: str
    node_id: str
    node_name: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: T


# ---------------------------------------------------------------------------
# SSE notification envelopes
# ---------------------------------------------------------------------------


class BaseThreadSseNotification(BaseModel, Generic[T]):
    """Envelope for thread-level SSE notifications.

    When serialized via :meth:`to_notify_payload`, produces the flat payload
    dict expected by ``centrifugo_mq.sse_notification.thread.notify()``.

    Attributes:
        thread_id: LangGraph thread UUID.
        event: SSE event name (e.g. ``"done"``, ``"thread_status"``).
        status: Terminal or transitional work/query status string.
        metadata: Arbitrary key/value bag for cross-cutting concerns.
        content: Biz-specific extra fields (e.g. ``{"error": "..."}``,
            ``{"reason": "..."}``).
    """

    thread_id: str
    event: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: T

    def to_notify_payload(self) -> dict[str, Any]:
        """Return the flat payload dict for centrifugo_mq thread notify().

        Spreads *content* fields at the top level alongside *status* so the
        published message matches the shape the frontend expects.
        ``thread_id`` and ``event`` are injected by ``notify()`` itself and
        are therefore excluded.
        """
        return {"status": self.status, **_content_to_dict(self.content)}


class BaseNodeSseNotification(BaseModel, Generic[T]):
    """Envelope for node-level SSE notifications.

    Attributes:
        thread_id: LangGraph thread UUID.
        node_id: Deterministic node identifier (``{thread_id}:{node_name}``).
        node_name: Human-readable node name.
        event: SSE event name (e.g. ``"node_status"``).
        status: Work status string.
        metadata: Arbitrary key/value bag for cross-cutting concerns.
        content: Biz-specific extra fields (e.g. ``{"input": {...}}``,
            ``{"output": {...}}``, ``{"reason": "..."}``).
    """

    thread_id: str
    node_id: str
    node_name: str
    event: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: T

    def to_notify_payload(self) -> dict[str, Any]:
        """Return the flat payload dict for centrifugo_mq node notify().

        Includes *status* and *node_name* at the top level alongside the
        spread *content* fields.  ``thread_id``, ``node_id``, and ``event``
        are injected by ``notify()`` itself and are excluded here.
        """
        return {
            "status": self.status,
            "node_name": strip_node_suffix(self.node_name),
            **_content_to_dict(self.content),
        }


class BaseTaskSseNotification(BaseModel, Generic[T]):
    """Envelope for task-level SSE notifications.

    Attributes:
        thread_id: LangGraph thread UUID.
        task_id: Unique task UUID.
        node_id: Owning node identifier (empty string when not available,
            e.g. during bulk thread-cancel).
        node_name: Human-readable node name (empty string when not available).
        task_name: Registered task name (empty string when not available).
        event: SSE event name (e.g. ``"task_status"``).
        status: Work status string.
        metadata: Arbitrary key/value bag for cross-cutting concerns.
        content: Biz-specific extra fields (e.g. ``{"input": {...}}``,
            ``{"output": {...}}``, ``{"reason": "..."}``).
    """

    thread_id: str
    task_id: str
    node_id: str = ""
    node_name: str = ""
    task_name: str = ""
    event: str
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    content: T

    def to_notify_payload(self) -> dict[str, Any]:
        """Return the flat payload dict for centrifugo_mq task notify().

        Includes *status*, *task_name*, *node_id*, and *node_name* at the top
        level alongside the spread *content* fields.  ``thread_id``,
        ``task_id``, and ``event`` are injected by ``notify()`` itself and are
        excluded here.
        """
        return {
            "status": self.status,
            "task_name": self.task_name,
            "node_id": self.node_id,
            "node_name": strip_node_suffix(self.node_name),
            **_content_to_dict(self.content),
        }
