"""Shared Pydantic models for the LangGraph node/task hierarchy."""

from backend.langgraph.models.base import (
    BaseNodeInput,
    BaseNodeOutput,
    BaseNodeSseNotification,
    BaseTaskInput,
    BaseTaskOutput,
    BaseTaskSseNotification,
    BaseThreadSseNotification,
)
from backend.langgraph.models.query import (
    AnalyzeQueryInput,
    AnalyzeQueryOutput,
)
from backend.langgraph.models.research import (
    MergeResultsInput,
    MergeResultsOutput,
    ReadNewsInput,
    ReadNewsOutput,
    ReadStatsInput,
    ReadStatsOutput,
)
from backend.langgraph.models.conclusion import (
    StreamConclusionInput,
    StreamConclusionOutput,
)

__all__ = [
    # Base envelopes
    "BaseNodeInput",
    "BaseNodeOutput",
    "BaseNodeSseNotification",
    "BaseTaskInput",
    "BaseTaskOutput",
    "BaseTaskSseNotification",
    "BaseThreadSseNotification",
    # query_node
    "AnalyzeQueryInput",
    "AnalyzeQueryOutput",
    # research_subgraph
    "ReadStatsInput",
    "ReadStatsOutput",
    "ReadNewsInput",
    "ReadNewsOutput",
    "MergeResultsInput",
    "MergeResultsOutput",
    # conclusion_node
    "StreamConclusionInput",
    "StreamConclusionOutput",
]
