CREATE SCHEMA IF NOT EXISTS fin_strategies;

CREATE TABLE IF NOT EXISTS fin_strategies.reports (
    id SERIAL PRIMARY KEY,
    symbol TEXT NOT NULL,
    short_term_technical_desc TEXT NOT NULL,
    long_term_technical_desc TEXT NOT NULL,
    news_desc TEXT NOT NULL,
    basic_biz_desc TEXT NOT NULL,
    industry_desc TEXT NOT NULL,
    significant_event_desc TEXT, -- earnings, product launches, M&A, etc.
    short_term_risk_desc TEXT, -- 1 or 2 weeks
    long_term_risk_desc TEXT, -- 6 months or more
    short_term_growth_desc TEXT, -- 1 or 2 weeks
    long_term_growth_desc TEXT, -- 6 months or more
    recent_trade_anomalies TEXT, -- signals of market manipulation, pricer suppression, etc.
    likely_today_fall_desc TEXT, -- near afternoon of trading day given morning data; if market not yet open, based on yesterday/history
    likely_tom_fall_desc TEXT,
    likely_short_term_fall_desc TEXT,
    likely_long_term_fall_desc TEXT,
    likely_today_rise_desc TEXT, -- near afternoon of trading day given morning data; if market not yet open, based on yesterday/history
    likely_tom_rise_desc TEXT,
    likely_short_term_rise_desc TEXT,
    likely_long_term_rise_desc TEXT,
    last_quote_quant_stats_id INT REFERENCES fin_markets.quant_stats(id),
    market_data_task_ids INT[], -- task ids of market data fetches used to generate this report, for traceability
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fin_strategies.reports
CREATE INDEX IF NOT EXISTS idx_reports_symbol ON fin_strategies.reports (symbol);
CREATE INDEX IF NOT EXISTS idx_reports_created_at ON fin_strategies.reports (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_reports_symbol_created_at ON fin_strategies.reports (symbol, created_at DESC);

