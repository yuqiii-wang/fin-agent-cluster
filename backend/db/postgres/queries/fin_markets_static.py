"""SQL templates for ``fin_markets.quant_static_stats``.

``quant_static_stats`` — financial report fundamentals per security; append-only rows keyed by
                         (symbol, created_at).  Optionally linked to a news article via
                         news_stats_id / published_at.
"""

from __future__ import annotations


class QuantStaticStatsSQL:
    """Queries against ``fin_markets.quant_static_stats``."""

    GET_LATEST = """
        SELECT
            id, symbol,
            revenue, revenue_yoy, gross_profit, operating_income, net_income, eps_diluted,
            gross_margin, operating_margin, net_margin,
            total_debt, shareholders_equity, debt_to_equity, free_cash_flow,
            pe_ratio, forward_pe, ev_ebitda, market_cap, dividend_per_share,
            published_at, news_stats_id,
            created_at
        FROM fin_markets.quant_static_stats
        WHERE symbol = %s
        ORDER BY created_at DESC
        LIMIT %s
    """

    INSERT = """
        INSERT INTO fin_markets.quant_static_stats (
            symbol,
            revenue, revenue_yoy, gross_profit, operating_income, net_income, eps_diluted,
            total_debt, shareholders_equity, free_cash_flow,
            pe_ratio, forward_pe, ev_ebitda, market_cap, dividend_per_share,
            published_at, news_stats_id
        ) VALUES (
            %(symbol)s,
            %(revenue)s, %(revenue_yoy)s, %(gross_profit)s, %(operating_income)s,
            %(net_income)s, %(eps_diluted)s,
            %(total_debt)s, %(shareholders_equity)s, %(free_cash_flow)s,
            %(pe_ratio)s, %(forward_pe)s, %(ev_ebitda)s, %(market_cap)s, %(dividend_per_share)s,
            %(published_at)s, %(news_stats_id)s
        )
        RETURNING id
    """
