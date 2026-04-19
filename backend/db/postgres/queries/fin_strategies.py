"""SQL templates for the ``fin_strategies`` schema.

Raw SQL strings parameterised for psycopg3 ``%s`` style.
"""


class ReportSQL:
    """Queries against ``fin_strategies.reports``."""

    INSERT = """
        INSERT INTO fin_strategies.reports (
            symbol,
            short_term_technical_desc,
            long_term_technical_desc,
            news_desc,
            basic_biz_desc,
            industry_desc,
            significant_event_desc,
            short_term_risk_desc,
            long_term_risk_desc,
            short_term_growth_desc,
            long_term_growth_desc,
            recent_trade_anomalies,
            likely_today_fall_desc,
            likely_tom_fall_desc,
            likely_short_term_fall_desc,
            likely_long_term_fall_desc,
            likely_today_rise_desc,
            likely_tom_rise_desc,
            likely_short_term_rise_desc,
            likely_long_term_rise_desc,
            last_quote_quant_stats_id,
            market_data_task_ids
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
        RETURNING *
    """

    GET_LATEST_BY_SYMBOL = """
        SELECT *
        FROM fin_strategies.reports
        WHERE symbol = %s
        ORDER BY created_at DESC
        LIMIT 1
    """

    GET_BY_ID = """
        SELECT *
        FROM fin_strategies.reports
        WHERE id = %s
        LIMIT 1
    """

    LIST_BY_SYMBOL = """
        SELECT *
        FROM fin_strategies.reports
        WHERE symbol = %s
        ORDER BY created_at DESC
        LIMIT %s OFFSET %s
    """
