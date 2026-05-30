"""SQL templates for ``fin_markets.quant_static_stats``.

``quant_static_stats`` — financial report fundamentals per security.
Anchor: ``(symbol, fin_report_date)`` where ``fin_report_date IS NOT NULL``.
  - New financial report (new ``fin_report_date``) → INSERT new row.
  - Re-fetch of same report period → UPSERT updates the existing row.
  - ``fin_report_date IS NULL`` (no report date available) → plain INSERT.
Optionally linked to a news article via ``news_stats_id`` / ``published_at``.
"""

from __future__ import annotations


class QuantStaticStatsSQL:
    """Queries against ``fin_markets.quant_static_stats``."""

    GET_LATEST = """
        SELECT
            id, symbol, fin_report_date,
            revenue, revenue_yoy, gross_profit, operating_income, net_income, eps_diluted,
            gross_margin, operating_margin, net_margin,
            total_debt, shareholders_equity, debt_to_equity, free_cash_flow,
            pe_ratio, forward_pe, ev_ebitda, market_cap,
            dividend_per_share, dividend_stability, dividend_record_date, dividend_payment_date,
            published_at, news_stats_id,
            primary_index_name, primary_index_weight,
            other_opt1_index_name, other_opt1_index_weight,
            other_opt2_index_name, other_opt2_index_weight,
            other_opt3_index_name, other_opt3_index_weight,
            analysis_estimate_price, analysis_estimate_date,
            created_at
        FROM fin_markets.quant_static_stats
        WHERE symbol = %s
        ORDER BY fin_report_date DESC NULLS LAST, created_at DESC
        LIMIT %s
    """

    # INSERT when fin_report_date IS NULL (no report anchor — always new row).
    # UPSERT when fin_report_date IS NOT NULL — ON CONFLICT updates all mutable
    # data columns so a re-fetch of the same period overwrites stale values.
    UPSERT = """
        INSERT INTO fin_markets.quant_static_stats (
            symbol, fin_report_date,
            revenue, revenue_yoy, gross_profit, operating_income, net_income, eps_diluted,
            total_debt, shareholders_equity, free_cash_flow,
            pe_ratio, forward_pe, ev_ebitda, market_cap,
            dividend_per_share, dividend_stability, dividend_record_date, dividend_payment_date,
            published_at, news_stats_id,
            primary_index_name, primary_index_weight,
            other_opt1_index_name, other_opt1_index_weight,
            other_opt2_index_name, other_opt2_index_weight,
            other_opt3_index_name, other_opt3_index_weight,
            analysis_estimate_price, analysis_estimate_date
        ) VALUES (
            %(symbol)s, %(fin_report_date)s,
            %(revenue)s, %(revenue_yoy)s, %(gross_profit)s, %(operating_income)s,
            %(net_income)s, %(eps_diluted)s,
            %(total_debt)s, %(shareholders_equity)s, %(free_cash_flow)s,
            %(pe_ratio)s, %(forward_pe)s, %(ev_ebitda)s, %(market_cap)s,
            %(dividend_per_share)s, %(dividend_stability)s,
            %(dividend_record_date)s, %(dividend_payment_date)s,
            %(published_at)s, %(news_stats_id)s,
            %(primary_index_name)s, %(primary_index_weight)s,
            %(other_opt1_index_name)s, %(other_opt1_index_weight)s,
            %(other_opt2_index_name)s, %(other_opt2_index_weight)s,
            %(other_opt3_index_name)s, %(other_opt3_index_weight)s,
            %(analysis_estimate_price)s, %(analysis_estimate_date)s
        )
        ON CONFLICT (symbol, fin_report_date)
        WHERE fin_report_date IS NOT NULL
        DO UPDATE SET
            revenue                 = EXCLUDED.revenue,
            revenue_yoy             = EXCLUDED.revenue_yoy,
            gross_profit            = EXCLUDED.gross_profit,
            operating_income        = EXCLUDED.operating_income,
            net_income              = EXCLUDED.net_income,
            eps_diluted             = EXCLUDED.eps_diluted,
            total_debt              = EXCLUDED.total_debt,
            shareholders_equity     = EXCLUDED.shareholders_equity,
            free_cash_flow          = EXCLUDED.free_cash_flow,
            pe_ratio                = EXCLUDED.pe_ratio,
            forward_pe              = EXCLUDED.forward_pe,
            ev_ebitda               = EXCLUDED.ev_ebitda,
            market_cap              = EXCLUDED.market_cap,
            dividend_per_share      = EXCLUDED.dividend_per_share,
            dividend_stability      = EXCLUDED.dividend_stability,
            dividend_record_date    = EXCLUDED.dividend_record_date,
            dividend_payment_date   = EXCLUDED.dividend_payment_date,
            published_at            = EXCLUDED.published_at,
            news_stats_id           = EXCLUDED.news_stats_id,
            primary_index_name      = EXCLUDED.primary_index_name,
            primary_index_weight    = EXCLUDED.primary_index_weight,
            other_opt1_index_name   = EXCLUDED.other_opt1_index_name,
            other_opt1_index_weight = EXCLUDED.other_opt1_index_weight,
            other_opt2_index_name   = EXCLUDED.other_opt2_index_name,
            other_opt2_index_weight = EXCLUDED.other_opt2_index_weight,
            other_opt3_index_name   = EXCLUDED.other_opt3_index_name,
            other_opt3_index_weight = EXCLUDED.other_opt3_index_weight,
            analysis_estimate_price = EXCLUDED.analysis_estimate_price,
            analysis_estimate_date  = EXCLUDED.analysis_estimate_date
        RETURNING id
    """
