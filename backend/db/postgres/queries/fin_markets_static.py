"""SQL templates for ``fin_markets.sec_profiles`` and ``fin_markets.quant_static_stats``.

``sec_profiles``       — one row per security; stores identity/profile data (name, intro,
                         cross-listing tickers, operating regions, currency).
``quant_static_stats`` — financial report fundamentals per security; append-only rows keyed by
                         (symbol, created_at).  Optionally linked to a news article via
                         news_stats_id / published_at.
"""

from __future__ import annotations


class SecProfileSQL:
    """Queries against ``fin_markets.sec_profiles``."""

    EXISTS = """
        SELECT 1
        FROM fin_markets.sec_profiles
        WHERE symbol = %s
        LIMIT 1
    """

    GET_BY_SYMBOL = """
        SELECT
            id, symbol, symbols, region, currency_code,
            name, biz_regions, intro, created_at, updated_at
        FROM fin_markets.sec_profiles
        WHERE symbol = %s
    """

    GET_BY_ANY_SYMBOL = """
        SELECT
            id, symbol, symbols, region, currency_code,
            name, biz_regions, intro, created_at, updated_at
        FROM fin_markets.sec_profiles
        WHERE symbol = %(symbol)s
           OR %(symbol)s = ANY(symbols)
        LIMIT 1
    """

    UPSERT = """
        INSERT INTO fin_markets.sec_profiles (
            symbol, symbols, region, currency_code,
            name, biz_regions, intro, updated_at
        ) VALUES (
            %(symbol)s, %(symbols)s, %(region)s, %(currency_code)s,
            %(name)s, %(biz_regions)s, %(intro)s, NOW()
        )
        ON CONFLICT (symbol) DO UPDATE SET
            symbols       = COALESCE(EXCLUDED.symbols,       fin_markets.sec_profiles.symbols),
            region        = COALESCE(EXCLUDED.region,        fin_markets.sec_profiles.region),
            currency_code = COALESCE(EXCLUDED.currency_code, fin_markets.sec_profiles.currency_code),
            name          = COALESCE(EXCLUDED.name,          fin_markets.sec_profiles.name),
            biz_regions   = COALESCE(EXCLUDED.biz_regions,   fin_markets.sec_profiles.biz_regions),
            intro         = COALESCE(EXCLUDED.intro,         fin_markets.sec_profiles.intro),
            updated_at    = NOW()
        RETURNING id, symbol
    """


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
