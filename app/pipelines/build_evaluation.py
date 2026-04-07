"""Pipeline: Assemble strategy evaluation context + all dimension tables.

Transform: Reads from multiple fin_markets tables and populates:
  fin_strategies.strategy_evaluation_context
  fin_strategies.sec_technicals       (A)
  fin_strategies.sec_fundamentals     (B)
  fin_strategies.sec_index_perf       (C)
  fin_strategies.sec_news_sentiment   (H)
  fin_strategies.sec_macro            (I)

This is the core "snapshot builder" that creates a complete evaluation
record for a security at a point in time, which the LLM agent then
reads to produce judgement_history.
"""

import logging
from decimal import Decimal
from typing import Any

from app.pipelines.base import BasePipeline

logger = logging.getLogger(__name__)


class BuildEvaluationPipeline(BasePipeline):
    """Build a complete strategy_evaluation_context snapshot for a security."""

    async def run(
        self,
        security_id: int,
        strategy_id: int,
        judgement_history_id: int,
        **kwargs: Any,
    ) -> int | None:
        """Assemble an evaluation context by reading latest data from fin_markets.

        Args:
            security_id: Target security.
            strategy_id: Strategy being applied.
            judgement_history_id: FK to the judgement being explained.

        Returns:
            evaluation_id (strategy_evaluation_context.id) or None on failure.
        """
        try:
            # --- Create header row ---
            ctx_rows = await self._execute(
                """
                INSERT INTO fin_strategies.strategy_evaluation_context
                    (judgement_history_id, strategy_id, security_id, snapshot_at)
                VALUES (%s, %s, %s, NOW())
                RETURNING id
                """,
                (judgement_history_id, strategy_id, security_id),
            )
            if not ctx_rows:
                return None
            eval_id = ctx_rows[0]["id"]

            # --- A: sec_technicals ---
            await self._build_technicals(eval_id, security_id)

            # --- B: sec_fundamentals ---
            await self._build_fundamentals(eval_id, security_id)

            # --- C: sec_index_perf ---
            await self._build_index_perf(eval_id, security_id)

            # --- H: sec_news_sentiment ---
            await self._build_news_sentiment(eval_id, security_id)

            # --- I: sec_macro ---
            await self._build_macro(eval_id)

            logger.info("Built evaluation context %d for security_id=%d", eval_id, security_id)
            return eval_id

        finally:
            await self.close()

    async def _build_technicals(self, eval_id: int, security_id: int) -> None:
        """Populate sec_technicals from latest trade_stat_aggregs.

        Args:
            eval_id: strategy_evaluation_context.id.
            security_id: Target security.
        """
        rows = await self._execute(
            """
            SELECT id, price, sma_20, sma_50, sma_200, ema_12, ema_26,
                   macd_signal, bollinger_std, price_52w_high, price_52w_low
            FROM fin_markets.security_trade_stat_aggregs
            WHERE security_id = %s ORDER BY published_at DESC LIMIT 1
            """,
            (security_id,),
        )
        if not rows:
            return
        s = rows[0]
        price = float(s["price"] or 0)
        sma_20 = float(s["sma_20"] or 0)
        sma_50 = float(s["sma_50"] or 0)
        sma_200 = float(s["sma_200"] or 0)
        ema_12 = float(s["ema_12"] or 0)
        ema_26 = float(s["ema_26"] or 0)
        bstd = float(s["bollinger_std"] or 0)
        p52h = float(s["price_52w_high"] or 0)
        p52l = float(s["price_52w_low"] or 0)

        macd = ema_12 - ema_26 if ema_12 and ema_26 else None
        macd_sig = float(s["macd_signal"] or 0)
        macd_hist = (macd - macd_sig) if macd is not None else None
        bb_upper = sma_20 + 2 * bstd if sma_20 and bstd else None
        bb_lower = sma_20 - 2 * bstd if sma_20 and bstd else None
        bb_pctb = ((price - bb_lower) / (bb_upper - bb_lower)) if bb_upper and bb_lower and bb_upper != bb_lower else None
        p52_pct = ((price - p52l) / (p52h - p52l)) if p52h != p52l else None
        vs_sma50 = ((price - sma_50) / sma_50) if sma_50 else None
        vs_sma200 = ((price - sma_200) / sma_200) if sma_200 else None

        await self._execute(
            """
            INSERT INTO fin_strategies.sec_technicals
                (evaluation_id, trade_stat_id, macd, macd_hist,
                 bollinger_upper, bollinger_lower, bb_pctb,
                 price_vs_sma50_pct, price_vs_sma200_pct, price_52w_pct)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (eval_id, s["id"], _d(macd), _d(macd_hist),
             _d(bb_upper), _d(bb_lower), _d(bb_pctb),
             _d(vs_sma50), _d(vs_sma200), _d(p52_pct)),
        )

    async def _build_fundamentals(self, eval_id: int, security_id: int) -> None:
        """Populate sec_fundamentals from latest security_exts + ext_aggregs.

        Args:
            eval_id: strategy_evaluation_context.id.
            security_id: Target security.
        """
        rows = await self._execute(
            """
            SELECT se.id, se.market_cap_usd, se.pe_ratio, se.pb_ratio, se.net_margin,
                   se.eps_ttm, se.revenue_ttm, se.debt_to_equity, se.dividend_yield,
                   sea.beta, sea.roe, sea.roa, sea.pe_forward, sea.ps_ratio, sea.ev_ebitda
            FROM fin_markets.security_exts se
            LEFT JOIN fin_markets.security_ext_aggregs sea ON sea.security_ext_id = se.id
            WHERE se.security_id = %s
            ORDER BY se.published_at DESC LIMIT 1
            """,
            (security_id,),
        )
        if not rows:
            return
        f = rows[0]
        await self._execute(
            """
            INSERT INTO fin_strategies.sec_fundamentals
                (evaluation_id, security_ext_id,
                 market_cap_usd, pe_ratio, pe_forward, pb_ratio,
                 ev_ebitda, ps_ratio, eps_ttm, revenue_ttm, net_margin,
                 roe, roa, debt_to_equity, dividend_yield, beta)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (eval_id, f["id"],
             f["market_cap_usd"], f["pe_ratio"], f.get("pe_forward"), f["pb_ratio"],
             f.get("ev_ebitda"), f.get("ps_ratio"), f["eps_ttm"], f["revenue_ttm"],
             f["net_margin"], f.get("roe"), f.get("roa"), f["debt_to_equity"],
             f["dividend_yield"], f.get("beta")),
        )

    async def _build_index_perf(self, eval_id: int, security_id: int) -> None:
        """Populate sec_index_perf from parent index data.

        Args:
            eval_id: strategy_evaluation_context.id.
            security_id: Target security.
        """
        # Find parent index via securities.parent_security_id
        rows = await self._execute(
            """
            SELECT s.parent_security_id, idx.id AS index_id
            FROM fin_markets.securities s
            LEFT JOIN fin_markets.indexes idx ON idx.security_id = s.parent_security_id
            WHERE s.id = %s AND s.parent_security_id IS NOT NULL
            """,
            (security_id,),
        )
        if not rows or not rows[0].get("index_id"):
            return

        index_id = rows[0]["index_id"]
        parent_sec_id = rows[0]["parent_security_id"]

        idx_stats = await self._execute(
            """
            SELECT ist.id, isa.weighted_return, isa.pct_above_sma_200,
                   isa.avg_pe, isa.index_volatility_20
            FROM fin_markets.index_stats ist
            LEFT JOIN fin_markets.index_stat_aggregs isa ON isa.index_stat_id = ist.id
            WHERE ist.index_id = %s
            ORDER BY ist.published_at DESC LIMIT 1
            """,
            (index_id,),
        )
        if not idx_stats:
            return
        ist = idx_stats[0]

        await self._execute(
            """
            INSERT INTO fin_strategies.sec_index_perf
                (evaluation_id, index_security_id, index_stat_id,
                 index_weighted_return_5d, index_pct_above_sma_200,
                 index_avg_pe, index_volatility_20)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (eval_id, parent_sec_id, ist["id"],
             ist["weighted_return"], ist["pct_above_sma_200"],
             ist["avg_pe"], ist["index_volatility_20"]),
        )

    async def _build_news_sentiment(self, eval_id: int, security_id: int) -> None:
        """Populate sec_news_sentiment from recent news_exts.

        Args:
            eval_id: strategy_evaluation_context.id.
            security_id: Target security.
        """
        rows = await self._execute(
            """
            SELECT
                COUNT(*) AS article_count,
                SUM(CASE WHEN ne.sentiment_level IN ('POSITIVE','VERY_POSITIVE') THEN 1 ELSE 0 END) AS pos_count,
                SUM(CASE WHEN ne.sentiment_level IN ('NEGATIVE','VERY_NEGATIVE') THEN 1 ELSE 0 END) AS neg_count,
                MAX(ne.id) AS latest_id
            FROM fin_markets.news_ext_2_security nes
            JOIN fin_markets.news_exts ne ON ne.id = nes.primary_id
            WHERE nes.related_id = %s
              AND ne.published_at > NOW() - INTERVAL '48 hours'
            """,
            (security_id,),
        )
        if not rows or rows[0]["article_count"] == 0:
            return
        r = rows[0]
        total = r["article_count"]
        pos_pct = round(r["pos_count"] / total * 100, 2) if total else None
        neg_pct = round(r["neg_count"] / total * 100, 2) if total else None

        await self._execute(
            """
            INSERT INTO fin_strategies.sec_news_sentiment
                (evaluation_id, news_latest_id, news_article_count,
                 news_positive_pct, news_negative_pct)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (eval_id, r["latest_id"], total, pos_pct, neg_pct),
        )

    async def _build_macro(self, eval_id: int) -> None:
        """Populate sec_macro from latest macro dynamics.

        Args:
            eval_id: strategy_evaluation_context.id.
        """
        # VIX from security_trade_stat_aggregs where ticker = 'VIX' or '^VIX'
        vix_rows = await self._execute(
            """
            SELECT sta.price, sta.interval_return
            FROM fin_markets.securities s
            JOIN LATERAL (
                SELECT price, interval_return
                FROM fin_markets.security_trade_stat_aggregs
                WHERE security_id = s.id
                ORDER BY published_at DESC LIMIT 1
            ) sta ON TRUE
            WHERE s.ticker IN ('VIX', '^VIX')
            LIMIT 1
            """
        )

        macro_vix = None
        if vix_rows:
            macro_vix = vix_rows[0]["price"]

        await self._execute(
            """
            INSERT INTO fin_strategies.sec_macro (evaluation_id, macro_vix)
            VALUES (%s, %s)
            """,
            (eval_id, macro_vix),
        )


def _d(v: float | None) -> Decimal | None:
    """Convert float to Decimal for DB insertion."""
    return Decimal(str(round(v, 6))) if v is not None else None
