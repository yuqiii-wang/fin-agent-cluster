CREATE SCHEMA IF NOT EXISTS fin_markets;

-- ============================================================
-- security_trade_stat_aggregs — additional technical indicator columns
-- Extends the min table created in fin_markets_2_ext_min.sql.
-- ============================================================
ALTER TABLE fin_markets.security_trade_stat_aggregs
    ADD COLUMN IF NOT EXISTS sma_5           NUMERIC(20,6),                           -- simple MA 5-period
    ADD COLUMN IF NOT EXISTS sma_120         NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS ema_50          NUMERIC(20,6),

    -- MACD family
    ADD COLUMN IF NOT EXISTS macd            NUMERIC(20,6),                           -- EMA12 - EMA26

    -- Momentum / oscillators
    ADD COLUMN IF NOT EXISTS williams_r      NUMERIC(10,4),                           -- Williams %R (14)
    ADD COLUMN IF NOT EXISTS cci_20          NUMERIC(12,4),                           -- commodity channel index
    ADD COLUMN IF NOT EXISTS mfi_14          NUMERIC(10,4),                           -- money flow index
    ADD COLUMN IF NOT EXISTS plus_di         NUMERIC(10,4),                           -- +DI (directional indicator)
    ADD COLUMN IF NOT EXISTS minus_di        NUMERIC(10,4),                           -- -DI

    -- Volatility
    ADD COLUMN IF NOT EXISTS bollinger_upper NUMERIC(20,6),                           -- BB upper (20, 2σ)
    ADD COLUMN IF NOT EXISTS bollinger_lower NUMERIC(20,6),                           -- BB lower
    ADD COLUMN IF NOT EXISTS bb_width        NUMERIC(10,6),                           -- (upper-lower)/mid
    ADD COLUMN IF NOT EXISTS bb_pctb         NUMERIC(10,6),                           -- %B position within bands

    -- Volume analysis
    ADD COLUMN IF NOT EXISTS volume_sma_20   BIGINT,                                  -- 20-day avg volume
    ADD COLUMN IF NOT EXISTS accumulation_distribution NUMERIC(20,6),                 -- A/D line

    -- Support / resistance / pivots
    ADD COLUMN IF NOT EXISTS pivot_point     NUMERIC(20,6),                           -- classic pivot (H+L+C)/3
    ADD COLUMN IF NOT EXISTS support_1       NUMERIC(20,6),                           -- S1
    ADD COLUMN IF NOT EXISTS resistance_1    NUMERIC(20,6),                           -- R1
    ADD COLUMN IF NOT EXISTS support_2       NUMERIC(20,6),
    ADD COLUMN IF NOT EXISTS resistance_2    NUMERIC(20,6),

    -- Ichimoku Cloud (extended spans)
    ADD COLUMN IF NOT EXISTS ichimoku_senkou_a   NUMERIC(20,6),                       -- leading span A
    ADD COLUMN IF NOT EXISTS ichimoku_senkou_b   NUMERIC(20,6),                       -- leading span B
    ADD COLUMN IF NOT EXISTS ichimoku_chikou     NUMERIC(20,6),                       -- lagging span

    -- Misc
    ADD COLUMN IF NOT EXISTS avg_price       NUMERIC(20,6);                           -- (O+H+L+C)/4

CREATE INDEX IF NOT EXISTS idx_ext_trade_stats_date     ON fin_markets.security_trade_stat_aggregs (published_at DESC);

-- ============================================================
-- security_exts — no additional columns beyond ext_min
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_ext_sec_exts_date        ON fin_markets.security_exts (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_ext_sec_exts_div_yield   ON fin_markets.security_exts (dividend_yield) WHERE dividend_yield IS NOT NULL;

-- ============================================================
-- security_ext_aggregs — additional fundamental & valuation columns
-- Extends the min table created in fin_markets_2_ext_min.sql.
-- ============================================================
ALTER TABLE fin_markets.security_ext_aggregs
    -- Valuation ratios (additional beyond min)
    ADD COLUMN IF NOT EXISTS pe_forward      NUMERIC(12,4),                           -- price / forward EPS estimate
    ADD COLUMN IF NOT EXISTS ps_ratio        NUMERIC(12,4),                           -- price / sales
    ADD COLUMN IF NOT EXISTS ev_ebitda       NUMERIC(12,4),                           -- enterprise value / EBITDA
    ADD COLUMN IF NOT EXISTS peg_ratio       NUMERIC(12,4),                           -- PE / earnings growth rate
    ADD COLUMN IF NOT EXISTS pcf_ratio       NUMERIC(12,4),                           -- price / cash flow

    -- Profitability & margins
    ADD COLUMN IF NOT EXISTS roe             NUMERIC(10,4),                           -- return on equity
    ADD COLUMN IF NOT EXISTS roa             NUMERIC(10,4),                           -- return on assets
    ADD COLUMN IF NOT EXISTS roic            NUMERIC(10,4),                           -- return on invested capital
    ADD COLUMN IF NOT EXISTS gross_margin    NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS operating_margin NUMERIC(10,4),

    -- Earnings (additional)
    ADD COLUMN IF NOT EXISTS eps_diluted     NUMERIC(12,4),
    ADD COLUMN IF NOT EXISTS ebitda_ttm      NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS net_income_ttm  NUMERIC(20,2),

    -- Balance sheet highlights
    ADD COLUMN IF NOT EXISTS total_debt      NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS total_cash      NUMERIC(20,2),
    ADD COLUMN IF NOT EXISTS current_ratio   NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS quick_ratio     NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS book_value_ps   NUMERIC(12,4),                           -- book value per share

    -- Dividends (additional)
    ADD COLUMN IF NOT EXISTS payout_ratio    NUMERIC(10,4),                           -- dividends / net income
    ADD COLUMN IF NOT EXISTS ex_dividend_date DATE,
    ADD COLUMN IF NOT EXISTS dividend_frequency TEXT CHECK (dividend_frequency IS NULL OR fin_markets.is_enum('dividend_frequency', dividend_frequency)), -- payment frequency

    -- Ownership & float
    ADD COLUMN IF NOT EXISTS shares_outstanding BIGINT,
    ADD COLUMN IF NOT EXISTS float_shares    BIGINT,
    ADD COLUMN IF NOT EXISTS insider_pct     NUMERIC(10,4),                           -- insider ownership %
    ADD COLUMN IF NOT EXISTS institutional_pct NUMERIC(10,4),                         -- institutional ownership %
    ADD COLUMN IF NOT EXISTS short_interest  BIGINT,                                  -- shares sold short
    ADD COLUMN IF NOT EXISTS short_ratio     NUMERIC(10,4),                           -- days to cover

    -- Analyst consensus (additional)
    ADD COLUMN IF NOT EXISTS analyst_target_price NUMERIC(12,4),                      -- consensus target
    ADD COLUMN IF NOT EXISTS analyst_count   INTEGER,
    ADD COLUMN IF NOT EXISTS earnings_surprise_pct NUMERIC(10,4),                     -- last quarter EPS surprise %

    -- Credit / fixed-income specific
    ADD COLUMN IF NOT EXISTS credit_rating   TEXT,                                    -- S&P/Moody's/Fitch
    ADD COLUMN IF NOT EXISTS yield_to_maturity NUMERIC(10,6),                         -- bonds
    ADD COLUMN IF NOT EXISTS coupon_rate     NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS maturity_date   DATE,
    ADD COLUMN IF NOT EXISTS duration        NUMERIC(10,4),                           -- modified duration
    ADD COLUMN IF NOT EXISTS convexity       NUMERIC(10,4),

    -- Beta / risk (additional)
    ADD COLUMN IF NOT EXISTS sharpe_ratio_1y NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS max_drawdown_1y NUMERIC(10,4);

-- Screening indexes on security_ext_aggregs
-- Single-column screener filters
CREATE INDEX IF NOT EXISTS idx_ext_stats_pe             ON fin_markets.security_exts (pe_ratio)             WHERE pe_ratio IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ext_stats_beta           ON fin_markets.security_ext_aggregs (beta)           WHERE beta IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ext_stats_revenue        ON fin_markets.security_exts (revenue_ttm)           WHERE revenue_ttm IS NOT NULL;
-- Multi-factor screener: pe_ratio lives on security_exts, beta on security_ext_aggregs (join required)
CREATE INDEX IF NOT EXISTS idx_ext_stats_pe_beta        ON fin_markets.security_exts (pe_ratio, security_id) WHERE pe_ratio IS NOT NULL;

-- ============================================================
-- index_stats — additional columns for extended index snapshots
-- Extends the min table created in fin_markets_2_ext_min.sql.
-- ============================================================
ALTER TABLE fin_markets.index_stats
    ADD COLUMN IF NOT EXISTS total_market_cap NUMERIC(24,2),                          -- sum of constituent market caps
    ADD COLUMN IF NOT EXISTS median_market_cap NUMERIC(20,2),                         -- median constituent market cap
    ADD COLUMN IF NOT EXISTS top10_weight    NUMERIC(10,6),                           -- concentration: sum of top-10 weights
    ADD COLUMN IF NOT EXISTS constituent_sec_ids BIGINT[];                            -- array of constituent security IDs

CREATE INDEX IF NOT EXISTS idx_ext_index_exts_date      ON fin_markets.index_stats (published_at DESC);

-- ============================================================
-- index_stat_aggregs — additional breadth/aggregate columns
-- Extends the min table created in fin_markets_2_ext_min.sql.
-- ============================================================
ALTER TABLE fin_markets.index_stat_aggregs
    -- Return aggregates (additional)
    ADD COLUMN IF NOT EXISTS avg_return      NUMERIC(10,6),                           -- equal-weight avg daily return
    ADD COLUMN IF NOT EXISTS median_return   NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS return_dispersion NUMERIC(10,6),                         -- stdev of constituent returns

    -- Breadth
    ADD COLUMN IF NOT EXISTS advance_count   INTEGER,                                 -- constituents up
    ADD COLUMN IF NOT EXISTS decline_count   INTEGER,                                 -- constituents down
    ADD COLUMN IF NOT EXISTS unchanged_count INTEGER,
    ADD COLUMN IF NOT EXISTS advance_decline_ratio NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS new_high_count  INTEGER,                                 -- 52-week highs
    ADD COLUMN IF NOT EXISTS new_low_count   INTEGER,                                 -- 52-week lows
    ADD COLUMN IF NOT EXISTS pct_above_sma_50  NUMERIC(10,4),                         -- % of constituents above 50-day MA

    -- Valuation aggregates (additional)
    ADD COLUMN IF NOT EXISTS avg_pb          NUMERIC(12,4),
    ADD COLUMN IF NOT EXISTS avg_ps          NUMERIC(12,4),
    ADD COLUMN IF NOT EXISTS avg_dividend_yield NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS earnings_yield  NUMERIC(10,6),                           -- 1 / avg_pe

    -- Volume
    ADD COLUMN IF NOT EXISTS total_volume    BIGINT,
    ADD COLUMN IF NOT EXISTS avg_volume_ratio NUMERIC(10,4),                          -- avg constituent vol / 20d avg

    -- Volatility (additional)
    ADD COLUMN IF NOT EXISTS index_volatility_60d NUMERIC(10,6),
    ADD COLUMN IF NOT EXISTS avg_constituent_vol  NUMERIC(10,6),                      -- avg constituent 20d vol

    -- Correlations (rolling 20-day; store other windows in extra)
    ADD COLUMN IF NOT EXISTS correlation_spx    NUMERIC(8,6),                         -- rolling corr with S&P 500
    ADD COLUMN IF NOT EXISTS correlation_dxy    NUMERIC(8,6),                         -- rolling corr with USD index
    ADD COLUMN IF NOT EXISTS correlation_us10y  NUMERIC(8,6),                         -- rolling corr with US 10Y yield
    ADD COLUMN IF NOT EXISTS correlation_vix    NUMERIC(8,6),                         -- rolling corr with VIX
    ADD COLUMN IF NOT EXISTS correlation_gold   NUMERIC(8,6),                         -- rolling corr with gold
    ADD COLUMN IF NOT EXISTS correlation_oil    NUMERIC(8,6);                         -- rolling corr with crude oil

CREATE INDEX IF NOT EXISTS idx_index_ext_stats_ext      ON fin_markets.index_stat_aggregs (index_stat_id);

-- ============================================================
-- 6. news_exts — additional AI-analysis columns
-- Extends the min table created in fin_markets_2_ext_min.sql.
-- ============================================================
ALTER TABLE fin_markets.news_exts
    ADD COLUMN IF NOT EXISTS sentiment_label fin_markets.sentiment_level,
    ADD COLUMN IF NOT EXISTS relevance_score NUMERIC(5,4),                            -- 0–1 relevance to financial markets
    ADD COLUMN IF NOT EXISTS confidence      NUMERIC(5,4),                            -- model confidence 0–1
    ADD COLUMN IF NOT EXISTS impacted_industries TEXT[],                              -- array of mentioned industries
    ADD COLUMN IF NOT EXISTS knowledge_graph JSONB;                                   -- extracted entities and relations

-- ============================================================
-- 8. macro_economics — additional macroeconomic release columns
-- Extends the min table created in fin_markets_2_ext_min.sql.
-- ============================================================
ALTER TABLE fin_markets.macro_economics
    ADD COLUMN IF NOT EXISTS indicator_name  TEXT,                                    -- Consumer Price Index YoY
    ADD COLUMN IF NOT EXISTS region          TEXT CHECK (region IS NULL OR fin_markets.is_enum('region', region)), -- geographic region
    ADD COLUMN IF NOT EXISTS reference_period TEXT;                                   -- 2025-Q1, 2025-03, 2025-W12

-- Indicator time-series: "all CPI releases over the past 2 years"
CREATE INDEX IF NOT EXISTS idx_macro_econ_indicator_date ON fin_markets.macro_economics (indicator_name, published_at DESC) WHERE indicator_name IS NOT NULL;

-- ============================================================
-- macro_economics_stats — additional derived columns for macro releases
-- Extends the min table created in fin_markets_2_ext_min.sql.
-- ============================================================
ALTER TABLE fin_markets.macro_economics_stats
    ADD COLUMN IF NOT EXISTS prev_value          NUMERIC(20,6),                       -- value from the immediately preceding period

    -- Period-over-period changes (absolute)
    ADD COLUMN IF NOT EXISTS value_mom           NUMERIC(12,6),                       -- month-over-month change
    ADD COLUMN IF NOT EXISTS value_qoq           NUMERIC(12,6),                       -- quarter-over-quarter change
    ADD COLUMN IF NOT EXISTS value_yoy           NUMERIC(12,6),                       -- year-over-year change

    -- Period-over-period changes (percent)
    ADD COLUMN IF NOT EXISTS value_mom_pct       NUMERIC(10,4),                       -- MoM % change
    ADD COLUMN IF NOT EXISTS value_qoq_pct       NUMERIC(10,4),                       -- QoQ % change
    ADD COLUMN IF NOT EXISTS value_yoy_pct       NUMERIC(10,4),                       -- YoY % change

    -- Surprise (additional)
    ADD COLUMN IF NOT EXISTS surprise            NUMERIC(12,6),                       -- actual − consensus

    -- Revision (prior period value restated after this release)
    ADD COLUMN IF NOT EXISTS revision_prev       NUMERIC(20,6),                       -- previously published prior-period value
    ADD COLUMN IF NOT EXISTS revision_delta      NUMERIC(12,6);                       -- restated − previously published

-- NOTE: macro_econ_id must match the actual FK column name in macro_economics_stats
-- when that table is defined; adjust before running.
CREATE INDEX IF NOT EXISTS idx_macro_econ_stats_macro_econ ON fin_markets.macro_economics_stats (macro_economics_id);

-- ============================================================
-- 9. macro_dynamics — additional columns for cross-asset snapshots
-- Extends the min table created in fin_markets_2_ext_min.sql.
-- ============================================================
ALTER TABLE fin_markets.macro_dynamics
    ADD COLUMN IF NOT EXISTS total_volume    BIGINT,                                  -- total constituent volume
    ADD COLUMN IF NOT EXISTS total_turnover  NUMERIC(20,2);                           -- total monetary turnover

-- ============================================================
-- macro_dynamics_stats — additional performance/breadth columns
-- Extends the min table created in fin_markets_2_ext_min.sql.
-- ============================================================
ALTER TABLE fin_markets.macro_dynamics_stats
    ADD COLUMN IF NOT EXISTS avg_change_pct  NUMERIC(10,6),                           -- avg daily return across constituents
    ADD COLUMN IF NOT EXISTS median_change_pct NUMERIC(10,6),

    -- Breadth (additional)
    ADD COLUMN IF NOT EXISTS advance_count   INTEGER,                                 -- # securities up
    ADD COLUMN IF NOT EXISTS decline_count   INTEGER,                                 -- # securities down
    ADD COLUMN IF NOT EXISTS unchanged_count INTEGER,
    ADD COLUMN IF NOT EXISTS advance_decline_ratio NUMERIC(10,4),
    ADD COLUMN IF NOT EXISTS new_high_count  INTEGER,                                 -- 52-week new highs
    ADD COLUMN IF NOT EXISTS new_low_count   INTEGER,                                 -- 52-week new lows
    ADD COLUMN IF NOT EXISTS pct_above_sma_50  NUMERIC(10,4),                         -- % of constituents above 50-day MA
    ADD COLUMN IF NOT EXISTS return_dispersion NUMERIC(10,6),                         -- stdev of constituent returns
    ADD COLUMN IF NOT EXISTS avg_volume_ratio  NUMERIC(10,4),                         -- avg vol / 20d avg vol

    -- Correlations (rolling 20-day; store other windows in extra)
    ADD COLUMN IF NOT EXISTS correlation_spx    NUMERIC(8,6),                         -- rolling corr with S&P 500
    ADD COLUMN IF NOT EXISTS correlation_dxy    NUMERIC(8,6),                         -- rolling corr with USD index
    ADD COLUMN IF NOT EXISTS correlation_us10y  NUMERIC(8,6),                         -- rolling corr with US 10Y yield
    ADD COLUMN IF NOT EXISTS correlation_vix    NUMERIC(8,6),                         -- rolling corr with VIX
    ADD COLUMN IF NOT EXISTS correlation_gold   NUMERIC(8,6),                         -- rolling corr with gold
    ADD COLUMN IF NOT EXISTS correlation_oil    NUMERIC(8,6),                         -- rolling corr with crude oil

    -- Money flow
    ADD COLUMN IF NOT EXISTS net_inflow      NUMERIC(20,2),                           -- buy turnover - sell turnover estimate
    ADD COLUMN IF NOT EXISTS large_order_inflow NUMERIC(20,2),                        -- large block net flow
    ADD COLUMN IF NOT EXISTS etf_flow        NUMERIC(20,2);                           -- related ETF creation/redemption

-- NOTE: idx_macro_dyn_date previously referenced here is now created in fin_markets_2_ext_min.sql
