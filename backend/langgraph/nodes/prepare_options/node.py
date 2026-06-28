"""PrepareOptionsNode -- Workflow node that fetches OHLCV bars and options stats
for the queried equity symbol via the shared ``get_and_calculate_stats`` pipeline.

Hierarchy
---------
Thread
  └── prepare_options (Workflow)
        ├── prepare_options_requests  (@task → proposes the full catalogue
        │                                of maturity windows as both
        │                                ``MaturityRequest`` and
        │                                ``PrepareOptionsRequestItem`` objects)
        ├── get_and_calculate_stats   (TaskSeq → OHLCV pipeline for symbol)
        └── get_and_calculate_stats × N (TaskSeq → options pipeline for symbol,
                                        one per proposed maturity window that
                                        fits within the node-level
                                        ``maturity_horizon``)

Node design
-----------
1. **Prepare phase``: Runs ``prepare_options_requests`` to obtain the full
   catalogue of available maturity windows (expressed as
   ``PrepareOptionsRequestItem`` objects -- directly consumable by
   ``get_and_calculate_stats``).

2. **OHLCV pipeline``: computes technical indicators from daily bars and
   upserts them into ``fin_markets.quant_stats`` (unchanged).

3. **Options pipelines``: for every ``PrepareOptionsRequestItem`` whose
   ``maturity_seconds`` fits within the node-level ``maturity_horizon`` a
   dedicated ``get_and_calculate_stats(pipeline='options',
   maturity_horizon=...)`` is launched.  The node owns the horizon decision
   -- ``prepare_options_requests`` no longer accepts a horizon input.

Predecessor
-----------
``query_node`` -- must be completed before ``prepare_options`` starts.
Runs in parallel with ``prepare_peers``, ``prepare_index``, ``prepare_news``,
``prepare_industry_news``, ``prepare_macro_news``, and ``prepare_futures``.
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
    PrepareOptionsOutput,
    PrepareOptionsRequestItem,
    PrepareOptionsRequestsInput,
    PrepareOptionsRequestsOutput,
)
from backend.langgraph.nodes.prepare_options.tasks.prepare_options_requests import (
    prepare_options_requests,
)
from backend.langgraph.state import GraphState
from backend.quant.stats.constants import OPTIONS_PERIODS

logger = logging.getLogger(__name__)

_OHLCV_PERIOD: str = "1y"
_OPTIONS_PERIOD: str = "1y"
_DEFAULT_OPTIONS_HORIZON: OPTIONS_PERIODS = (
    OPTIONS_PERIODS.ONE_YEAR
)


def _coerce_horizon_seconds(value: object) -> int:
    """Normalise any supported horizon representation to a raw seconds int.

    Accepts:
      * ``None`` → ``ONE_YEAR.seconds``.
      * A ``OPTIONS_PERIODS`` member.
      * A string matching ``display_name`` or ``name``.
      * A raw int / float seconds (snapped to the enum member with the
        largest ``seconds`` still <= the value).
      * A ``(display_name, seconds)`` tuple.

    Returns:
        The raw seconds of the chosen enum member.
    """

    if value is None:
        return int(_DEFAULT_OPTIONS_HORIZON.seconds)
    if isinstance(value, OPTIONS_PERIODS):
        return int(value.seconds)
    if isinstance(value, str):
        key = value.strip().lower().replace("_", " ")
        if not key:
            return int(_DEFAULT_OPTIONS_HORIZON.seconds)
        for member in OPTIONS_PERIODS:
            if member.display_name.lower() == key or member.name.lower() == key:
                return int(member.seconds)
        try:
            seconds = int(float(key))
        except ValueError as exc:
            raise ValueError(
                f"maturity_horizon string {value!r} is not a recognised "
                f"OPTIONS_PERIODS label."
            ) from exc
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
    ordered = sorted(OPTIONS_PERIODS, key=lambda m: m.seconds)
    chosen = ordered[0]
    for member in ordered:
        if member.seconds <= seconds:
            chosen = member
        else:
            break
    return int(chosen.seconds)


class PrepareOptionsNode(BaseNode[PrepareOptionsInput, PrepareOptionsOutput]):
    """Workflow node: OHLCV + options stats for the queried equity symbol."""

    node_name = "prepare_options"
    node_type = NodeType.WORKFLOW
    display_name = "Prepare Options"
    category = "Analysis"
    parallel_group: ClassVar[str] = "analyze_parallel"

    # ``prepare_options_requests`` must be first so LangGraph dispatches it
    # before any of the stats pipelines it plans; the shared task seq's
    # get_and_calculate_stats is expanded inline so every sub-task is
    # registered here too.
    tasks: ClassVar[list[NodeTask]] = [
        prepare_options_requests, *get_and_calculate_stats.tasks]

    _prev_node_names: ClassVar[list[str]] = ["query_node"]

    async def build_input(self, state: GraphState) -> PrepareOptionsInput:
        """Read stock_symbol from query_node's completed node_executions row.

        Args:
            state: Current GraphState.

        Returns:
            :class:`PrepareOptionsInput` with the resolved symbol and default
            stats periods.  ``maturity_horizon`` is set to
            ``OPTIONS_PERIODS.ONE_YEAR`` by default.  This is the
            single place the horizon lives -- it is intentionally NOT forwarded
            to ``prepare_options_requests``; this node filters the returned
            plan instead.
        """

        query_node_id = self._find_node_id_by_name(state, "query_node")
        stock_symbol = ""
        if query_node_id:
            output = await read_node_output(query_node_id)
            stock_symbol = output.get("stock_name", "")
        if not stock_symbol:
            logger.warning("[PO-001] No stock_symbol from query_node; prepare_options will skip.")
        return PrepareOptionsInput(
            stock_symbol=stock_symbol,
            ohlcv_period=_OHLCV_PERIOD,
            options_period=_OPTIONS_PERIOD,
            maturity_horizon=_DEFAULT_OPTIONS_HORIZON,
        )

    def build_chain(
        self, ctx: NodeContext,
    ) -> Runnable[PrepareOptionsInput, dict[str, Any]]:
        """Run three phases: propose maturities, then OHLCV + per-maturity options.

        Phase 1 — ``prepare_options_requests``: returns the full catalogue of
        available maturity windows.  ``maturity_horizon`` is intentionally
        **not** passed to this task; it is used in Phase 3 to filter which
        windows to actually run.

        Phase 2 — parallel fan-out: one ``get_and_calculate_stats`` pipeline
        for the OHLCV symbol, plus one ``get_and_calculate_stats`` per
        ``PrepareOptionsRequestItem`` whose ``maturity_seconds`` fits within
        ``PrepareOptionsInput.maturity_horizon``.

        Args:
            ctx: Current node context carrying thread/node/task identity.

        Returns:
            Runnable that produces a dict with ``results`` and
            ``df_splits`` keys, consumed by :meth:`build_output`.
        """

        async def _run(node_input: PrepareOptionsInput) -> dict[str, Any]:
            results: list[OptionsStatResult] = []
            df_splits: list[dict[str, Any]] = []

            if not node_input.stock_symbol:
                return {"results": results, "df_splits": df_splits}

            # Phase 1 — propose maturities; note: we intentionally do NOT
            # pass the node-level maturity_horizon to this task. The node
            # does its own filtering in Phase 3.
            try:
                plan_output = await self.run_task(
                    prepare_options_requests,
                    ctx,
                    PrepareOptionsRequestsInput(
                        stock_symbol=node_input.stock_symbol,
                        include_next=True,
                    ),
                )
                plan: PrepareOptionsRequestsOutput = plan_output.content
                horizon_seconds = _coerce_horizon_seconds(node_input.maturity_horizon)
                logger.info(
                    "prepare_options plan symbol=%r horizon_seconds=%d "
                    "maturities=%d requests=%d",
                    node_input.stock_symbol,
                    horizon_seconds,
                    len(plan.maturities),
                    len(plan.requests),
                )
            except Exception as exc:
                logger.error("[PO-003] prepare_options_requests failed: %s", exc)
                raise

            # Phase 2 — fan out: OHLCV pipeline + one options pipeline per
            # maturity within the node-level horizon.
            async def _run_ohlcv() -> None:
                try:
                    seq_out = await get_and_calculate_stats.run(
                        self.run_task,
                        ctx,
                        GetAndCalculateStatsInput(
                            symbol=node_input.stock_symbol,
                            period=node_input.ohlcv_period,
                            pipeline="ohlcv",
                        ),
                    )
                    calc = seq_out.calculate_stats
                    rows = int(getattr(calc, "rows_upserted", 0) or 0)
                    results.append(
                        OptionsStatResult(
                            pipeline="ohlcv",
                            symbol=node_input.stock_symbol,
                            rows_upserted=rows,
                            from_cache=bool(seq_out.get_stats.from_cache),
                        )
                    )
                    df_split = getattr(calc, "df_split", None)
                    if df_split:
                        df_splits.append(
                            {
                                "symbol": node_input.stock_symbol,
                                "label": f"{node_input.stock_symbol} (ohlcv)",
                                "df_split": df_split,
                            }
                        )
                except Exception as exc:
                    logger.error(
                        "[PO-002] ohlcv pipeline failed symbol=%r: %s",
                        node_input.stock_symbol, exc,
                    )

            async def _run_one_maturity(req: PrepareOptionsRequestItem) -> None:
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
                            rows_upserted=rows,
                            from_cache=bool(seq_out.get_stats.from_cache),
                        )
                    )
                except Exception as exc:
                    logger.error(
                        "[PO-004] options pipeline failed symbol=%r label=%r: %s",
                        req.symbol, req.maturity_label, exc,
                    )

            awaitables: list[Any] = [_run_ohlcv()]

            # Filter the proposed windows by the node-level horizon so we
            # don't waste time on maturities the caller doesn't want.
            for item in plan.requests:
                if item.maturity_seconds is None:
                    continue
                if item.maturity_seconds > horizon_seconds:
                    continue
                # Override period / symbol with the current node's inputs so
                # a single plan can be reused for different symbols/periods.
                item = PrepareOptionsRequestItem(
                    symbol=node_input.stock_symbol,
                    period=node_input.options_period,
                    pipeline=item.pipeline,
                    maturity_horizon=item.maturity_horizon,
                    maturity_label=item.maturity_label,
                    maturity_seconds=item.maturity_seconds,
                )
                awaitables.append(_run_one_maturity(item))

            await asyncio.gather(*awaitables)

            return {"results": results, "df_splits": df_splits}

        return RunnableLambda(_run)

    def build_output(self, results: dict[str, Any]) -> PrepareOptionsOutput:
        """Compose node output from the parallel pipeline results.

        Args:
            results: Keyed outputs from :meth:`build_chain`'s Runnable.

        Returns:
            :class:`PrepareOptionsOutput` with per-pipeline summaries,
            including one entry per executed maturity window for options.
        """
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
prepare_options_node = PrepareOptionsNode()
