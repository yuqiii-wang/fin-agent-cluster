"""LoadSymbolStatsNode -- Workflow node that runs the
``get_and_calculate_stats`` (gacs) branch for the queried equity symbol:

1. Resolve a market-data StatsRecord (OHLCV) via ``get_stats``.
2. Compute technical indicators and upsert into ``fin_markets.quant_stats``
   via ``calculate_stats``.

Hierarchy
---------
Thread
  └── load_symbol_stats  (WORKFLOW node)
        └── gacs branch
              └── get_stats -> calculate_stats
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

from langchain_core.runnables import Runnable, RunnableLambda

from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle import read_node_output
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.calculate_stats import (
    CalculateStatsInput,
    calculate_stats,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.get_stats import (
    GetStatsInput,
    get_stats,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats.models import (
    GetAndCalculateStatsOutput,
)
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.load_symbol_stats.models import (
    BranchAttempt,
    LoadSymbolStatsInput,
    LoadSymbolStatsNodeOutput,
)
from backend.langgraph.state import GraphState

logger = logging.getLogger(__name__)


async def _run_gacs_branch(
    run_task_fn: Any,
    ctx: NodeContext,
    *,
    symbol: str,
    period: str,
    pipeline: str,
    attempts_out: list[BranchAttempt],
) -> GetAndCalculateStatsOutput | None:
    """Run ``get_stats`` -> ``calculate_stats``.

    Records a single attempt in *attempts_out* for audit history.
    Returns the branch output or ``None`` on failure.
    """
    try:
        gs_result = await run_task_fn(
            get_stats,
            ctx,
            GetStatsInput(
                symbol=symbol,
                period=period,
                pipeline=pipeline,
            ),
        )
        gs_output = gs_result.content
        effective_pipeline = (
            pipeline
            or getattr(gs_output, "pipeline", None)
            or "ohlcv"
        )
        cs_result = await run_task_fn(
            calculate_stats,
            ctx,
            CalculateStatsInput(
                stats_record=gs_output.stats_record,
                from_cache=getattr(gs_output, "from_cache", False)
                or effective_pipeline != "ohlcv",
                pipeline=effective_pipeline,
            ),
        )
        out = GetAndCalculateStatsOutput(
            get_stats=gs_output,
            calculate_stats=cs_result.content,
        )
        attempts_out.append(
            BranchAttempt(
                branch="gacs",
                attempt=1,
                ok=True,
                reason="ok",
                orchestration_action=None,
                orchestration_reasoning=None,
                extra={},
            )
        )
        return out
    except Exception as exc:
        last_error = str(exc)
        logger.warning(
            "[load_symbol_stats] gacs branch failed for symbol=%s: %s",
            symbol, exc,
        )
        attempts_out.append(
            BranchAttempt(
                branch="gacs",
                attempt=1,
                ok=False,
                reason=last_error[:600] + (" ...[truncated]" if len(last_error) > 600 else ""),
                orchestration_action=None,
                orchestration_reasoning=None,
                extra={},
            )
        )
        return None


class LoadSymbolStatsNode(
    BaseNode[LoadSymbolStatsInput, LoadSymbolStatsNodeOutput]
):
    """Workflow node: run the gacs branch for the queried symbol."""

    node_name = "load_symbol_stats"
    node_type = NodeType.WORKFLOW
    display_name = "Load Symbol Stats"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"
    config_fields: ClassVar[list[dict]] = [
        {
            "key": "period",
            "label": "Market-data period (forwarded to get_stats)",
            "type": "select",
            "options": [
                {"value": "1d", "label": "1 day"},
                {"value": "5d", "label": "5 days"},
                {"value": "1mo", "label": "1 month"},
                {"value": "3mo", "label": "3 months"},
                {"value": "6mo", "label": "6 months"},
                {"value": "1y", "label": "1 year"},
                {"value": "2y", "label": "2 years"},
                {"value": "5y", "label": "5 years"},
            ],
            "default": "2y",
        },
        {
            "key": "pipeline",
            "label": "Pipeline label forwarded to calculate_stats",
            "type": "select",
            "options": [
                {"value": "ohlcv", "label": "OHLCV"},
                {"value": "options", "label": "Options"},
                {"value": "futures", "label": "Futures"},
            ],
            "default": "ohlcv",
        },
    ]
    view_type = "Stats"
    stats_views: ClassVar[list[str]] = []
    tasks: ClassVar[list[NodeTask]] = [
        get_stats,
        calculate_stats,
    ]
    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(
        self, state: GraphState
    ) -> LoadSymbolStatsInput:
        """Read ``stock_name`` from ``query_node``'s output row.

        Args:
            state: Current GraphState.

        Returns:
            :class:`LoadSymbolStatsInput` with the resolved stock symbol.
        """
        query_node_id = self._find_node_id_by_name(state, "query_node")
        stock_symbol = ""
        if query_node_id:
            output = await read_node_output(query_node_id)
            stock_symbol = output.get("stock_name", "") or ""
        return LoadSymbolStatsInput(stock_symbol=stock_symbol)

    def build_chain(
        self, ctx: NodeContext
    ) -> Runnable[LoadSymbolStatsInput, dict]:
        """Run the gacs branch.

        Args:
            ctx: Node context carrying thread/node/task identity.

        Returns:
            Runnable that accepts :class:`LoadSymbolStatsInput` and
            produces a plain ``dict`` keyed by branch label plus
            a ``__summary__`` entry used by ``build_output``.
        """

        async def _run(
            node_input: LoadSymbolStatsInput,
        ) -> dict:
            symbol = (node_input.stock_symbol or "").strip().upper()
            period = node_input.period or "2y"
            pipeline = node_input.pipeline or "ohlcv"

            gacs_attempts: list[BranchAttempt] = []

            gacs_result = await _run_gacs_branch(
                self.run_task,
                ctx,
                symbol=symbol,
                period=period,
                pipeline=pipeline,
                attempts_out=gacs_attempts,
            )

            gacs_dump: Any = None
            attempts_dump: list[dict] = []
            try:
                if gacs_result is not None and hasattr(gacs_result, "model_dump"):
                    gacs_dump = gacs_result.model_dump(mode="json")
                else:
                    gacs_dump = gacs_result if gacs_result is not None else None
                attempts_dump = [a.model_dump(mode="json") for a in gacs_attempts]
            except Exception as exc:
                logger.exception(
                    "[load_symbol_stats] serialising gacs output failed for symbol=%s: %s",
                    symbol, exc,
                )
                gacs_dump = None
                fallback_attempts = attempts_dump if attempts_dump else [
                    BranchAttempt(
                        branch="gacs",
                        attempt=max(a.attempt for a in gacs_attempts) if gacs_attempts else 1,
                        ok=False,
                        reason=f"serialisation_error: {str(exc)[:500]}",
                        orchestration_action=None,
                        orchestration_reasoning=None,
                        extra={},
                    ).model_dump(mode="json")
                ]
                attempts_dump = fallback_attempts

            summary = LoadSymbolStatsNodeOutput(
                symbol=symbol,
                gacs=gacs_dump,
                attempts=attempts_dump,
            )

            return {
                "gacs": gacs_result,
                "__summary__": summary,
            }

        return RunnableLambda(_run)  # type: ignore[arg-type]

    def build_output(
        self, results: dict
    ) -> LoadSymbolStatsNodeOutput:
        """Compose the node output from ``build_chain``'s ``__summary__``.

        Args:
            results: Keyed outputs from the chain.

        Returns:
            :class:`LoadSymbolStatsNodeOutput` summarising the gacs branch.
        """
        summary_entry = results.get("__summary__")
        if summary_entry is None:
            return LoadSymbolStatsNodeOutput(
                symbol="",
                gacs=None,
                attempts=[],
            )
        if isinstance(summary_entry, LoadSymbolStatsNodeOutput):
            return summary_entry
        return LoadSymbolStatsNodeOutput.model_validate(summary_entry)

    def get_state_updates(
        self, output: LoadSymbolStatsNodeOutput
    ) -> dict[str, Any]:
        """No GraphState updates -- data flows via DB."""
        return {}


load_symbol_stats_node = LoadSymbolStatsNode()
