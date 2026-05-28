"""Output model for prepare_derivatives node."""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = ["PrepareDerivativesOutput"]


class PrepareDerivativesOutput(BaseModel):
    """Typed output for ``prepare_derivatives``.

    Persisted to ``fin_agents.node_executions`` for downstream nodes.

    Attributes:
        symbol:             Underlying equity ticker, e.g. ``'AAPL'``.
        web_knowledge_url:  URL that was studied via navigate_web to gather
                            derivatives market knowledge for this symbol.
        stats_views:        Node-level stats view types; always ``['DerivativesFlow']``.
    """

    symbol: str = Field(description="Underlying equity ticker.")
    web_knowledge_url: str = Field(
        default="",
        description="Yahoo Finance options URL studied for derivatives knowledge.",
    )
    stats_views: list[str] = Field(
        default_factory=lambda: ["DerivativesFlow"],
        description="Node-level stats view types.",
    )

