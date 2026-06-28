"""PrepareFuturesNode -- Workflow node that fetches OHLCV bars for the
queried symbol across multiple aggregation windows defined by
:class:`~backend.quant.stats.constants.FUTURES_PERIODS`.

The node mirrors :class:`PrepareOptionsNode` in structure:

1. ``prepare_futures_requests`` proposes the full catalogue of windows.
2. The hosting node filters windows by its own ``maturity_horizon``.
3. A fan-out of ``get_and_calculate_stats(pipeline="futures")`` calls is
   issued concurrently, one per window.

Crucially, futures bars share the same ``OhlcvStatsMatrix`` shape as plain
equities -- the difference is routing: each bar is tagged with
``pipeline="futures"`` and the underlying ``StatsRecord.id`` is prefixed
``yf-futures-`` (so downstream renderers / caches can distinguish futures
bars from plain equity bars without re-running symbol heuristics).

Predecessor
-----------
``query_node`` -- must be completed before ``prepare_futures`` starts.
Runs in parallel with ``prepare_peers``, ``prepare_index``,
``prepare_news``, ``prepare_industry_news``, and ``prepare_options``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar

from langchain_core.runnables import Runnable, RunnableLambda

from backend.db.postgres.types import NodeType
from backend.langgraph.lifecycle import read_node_output
from backend.langgraph.models.common_tasks.task_seqs.get_and_calculate_stats import (
    GetAndCalculateStatsInput,
    get_and_calculate_stats,
)
from backend.langgraph.models.models import NodeContext
from backend.langgraph.models.node import BaseNode
from backend.langgraph.models.task import NodeTask
from backend.langgraph.nodes.prepare_options.models import (
    OptionsStatResult,
    PrepareOptionsInput,
    PrepareOptionsRequestItem,
    PrepareOptionsRequestsInput,
    PrepareOptionsRequestsOutput,
    PrepareOptionsOutput,
)
from backend.langgraph.nodes.prepare_futures.tasks.prepare_futures_requests import (
    prepare_futures_requests,
)
from backend.quant.stats.constants import FUTURES_PERIODS

logger = logging.getLogger(__name__)

_DEFAULT_HORIZON: FUTURES_PERIODS = FUTURES_PERIODS.ONE_YEAR


def _coerce_horizon_seconds(value: object) -> int:
    """Normalise any supported horizon representation to a raw seconds int.

    Accepts:
      * ``None`` → ``ONE_YEAR.seconds``.
      * A ``FUTURES_PERIODS`` member.
      * A string matching ``display_name`` or ``name``.
      * A raw int / float seconds (snapped to the largest enum member
        whose seconds are still <= the value).
      * A ``(display_name, seconds)`` tuple.

    Returns:
        The raw seconds of the chosen enum member.
    """

    if value is None:
        return int(_DEFAULT_HORIZON.seconds)
    if isinstance(value, FUTURES_PERIODS):
        return int(value.seconds)
    if isinstance(value, str):
        key = value.strip().lower().replace("_", " ")
        if not key:
            return int(_DEFAULT_HORIZON.seconds)
        for member in FUTURES_PERIODS:
            if member.display_name.lower() == key or member.name.lower() == key:
                return int(member.seconds)
        try:
            seconds = int(float(key))
        except ValueError:
            raise ValueError(
                f"maturity_horizon string {value!r} is not a recognised "
                f"FUTURES_PERIODS label."
            )
        return _snap_seconds(seconds)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _snap_seconds(int(value))
    if isinstance(value, (tuple, list)) and len(value) == 2:
        try:
            seconds = int(value[1])
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"maturity_horizon tuple[1] is not an int seconds value: {value}"
            ) from exc
        return _snap_seconds(seconds)
    raise ValueError(f"Unsupported maturity_horizon value: {value!r}")


def _snap_seconds(seconds: int) -> int:
    """Snap a raw ``seconds`` to the nearest-fitting enum member's seconds."""

    if seconds < 0:
        raise ValueError(f"maturity_horizon seconds must be >= 0, got {seconds}")
    ordered = sorted(FUTURES_PERIODS, key=lambda m: m.seconds)
    chosen = ordered[0]
    for member in ordered:
        if member.seconds <= seconds:
            chosen = member
        else:
            break
    return int(chosen.seconds)


class PrepareFuturesNode(BaseNode[PrepareOptionsInput, PrepareOptionsOutput]):
    """Workflow node: multi-window OHLCV for futures pipeline."""

    node_name = "prepare_futures"
    node_type = NodeType.WORKFLOW
    display_name = "Prepare Futures"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"

    # ``prepare_futures_requests`` must be first so LangGraph dispatches it
    # before any of the stats pipelines it plans.
    tasks: ClassVar[list[NodeTask]] = [
        prepare_futures_requests,
        *get_and_calculate_stats.tasks,
    ]

    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(self, state: Any) -> PrepareOptionsInput:
        """Read stock_symbol from query_node's completed node_executions row."""

        query_node_id = self._find_node_id_by_name(state, "query_node")
        stock_symbol = ""
        if query_node_id:
            output = await read_node_output(query_node_id)
            stock_symbol = output.get("stock_name", "") or ""
        if not stock_symbol:
            logger.warning("[PF-001] No stock_symbol from query_node; prepare_futures will skip.")
        return PrepareOptionsInput(
            stock_symbol=stock_symbol,
            ohlcv_period="1y",
            options_period="1y",
            maturity_horizon=_DEFAULT_HORIZON,
        )

    def build_chain(
        self,
        ctx: NodeContext,
    ) -> Runnable[PrepareOptionsInput, dict[str, Any]]:
        """Run two phases: propose windows, then parallel fan-out of futures pipelines."""

        async def _run(node_input: PrepareOptionsInput) -> dict[str, Any]:
            results: list[OptionsStatResult] = []
            df_splits: list[dict[str, Any]] = []

            if not node_input.stock_symbol:
                return {"results": results, "df_splits": df_splits}

            # Phase 1 -- propose the full catalogue of windows.
            try:
                plan_output = await self.run_task(
                    prepare_futures_requests,
                    ctx,
                    PrepareOptionsRequestsInput(
                        stock_symbol=node_input.stock_symbol,
                        include_next=True,
                    ),
                )
                plan: PrepareOptionsRequestsOutput = plan_output.content
                horizon_seconds = _coerce_horizon_seconds(node_input.maturity_horizon)
                logger.info(
                    "prepare_futures plan symbol=%r horizon_seconds=%d "
                    "maturities=%d requests=%d",
                    node_input.stock_symbol,
                    horizon_seconds,
                    len(plan.maturities),
                    len(plan.requests),
                )
            except Exception as exc:
                logger.error("[PF-003] prepare_futures_requests failed: %s", exc)
                raise

            # Phase 2 -- fan out: one get_and_calculate_stats per window
            # within the node-level horizon.
            async def _run_one(req: PrepareOptionsRequestItem) -> None:
                try:
                    seq_out = await get_and_calculate_stats.run(
                        self.run_task,
                        ctx,
                        GetAndCalculateStatsInput(
                            symbol=req.symbol,
                            period=req.period,
                            pipeline=req.pipeline,
                            maturity_horizon=req.maturity_horizon,
                        ),
                    )
                    calc = seq_out.calculate_stats
                    rows = int(getattr(calc, "rows_upserted", 0) or 0)
                    results.append(
                        OptionsStatResult(
                            pipeline=req.pipeline,
                            symbol=req.symbol,
                            maturity_label=req.maturity_label,
                            maturity_seconds=req.maturity_seconds,
                            rows_upserted=rows,
                            from_cache=bool(seq_out.get_stats.from_cache),
                        )
                    )
                    df_split = getattr(calc, "df_split", None)
                    if df_split:
                        df_splits.append(
                            {
                                "symbol": req.symbol,
                                "label": f"{req.symbol} ({req.maturity_label})",
                                "df_split": df_split,
                            }
                        )
                except Exception as exc:
                    logger.error(
                        "[PF-004] futures pipeline failed symbol=%r label=%r: %s",
                        req.symbol, req.maturity_label, exc,
                    )

            awaitables: list[Any] = []
            for item in plan.requests:
                if item.maturity_seconds is None:
                    continue
                if item.maturity_seconds > horizon_seconds:
                    continue
                # Override symbol/period with the current node's inputs so
                # a single plan can be reused for different symbols/periods.
                item = PrepareOptionsRequestItem(
                    symbol=node_input.stock_symbol,
                    period=item.period,
                    pipeline=item.pipeline,
                    maturity_horizon=item.maturity_horizon,
                    maturity_label=item.maturity_label,
                    maturity_seconds=item.maturity_seconds,
                )
                awaitables.append(_run_one(item))

            if awaitables:
                await asyncio.gather(*awaitables)

            return {"results": results, "df_splits": df_splits}

        return RunnableLambda(_run)

    def build_output(self, results: dict[str, Any]) -> PrepareOptionsOutput:
        """Compose node output from the parallel pipeline results."""

        symbol = ""
        items = results.get("results") or []
        if items:
            symbol = str(getattr(items[0], "symbol", ""))
        return PrepareOptionsOutput(
            stock_symbol=symbol,
            results=items,
            df_splits=(results.get("df_splits") or []),
        )

    def get_state_updates(self, output: PrepareOptionsOutput) -> dict[str, Any]:
        """No GraphState updates -- data flows via DB."""
        return {}


# Module-level callable registered with LangGraph StateGraph.
prepare_futures_node = PrepareFuturesNode()
