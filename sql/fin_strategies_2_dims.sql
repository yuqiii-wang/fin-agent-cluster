CREATE SCHEMA IF NOT EXISTS fin_strategies;

-- ============================================================
-- strategies — named strategy registry
-- Serves as the FK target for judgement_history.strategy_id and
-- strategy_evaluation_context.strategy_id.
-- config JSONB holds strategy-specific tuning parameters
-- (lookback windows, signal weights, threshold overrides, etc.)
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.strategies (
    id              BIGSERIAL       PRIMARY KEY,
    name            TEXT            NOT NULL UNIQUE,        -- e.g. 'multi_signal_v1'
    version         TEXT            NOT NULL DEFAULT '1.0',
    description     TEXT,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    config          JSONB           NOT NULL DEFAULT '{}',  -- tuning params (lookback, weights, etc.)
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);


-- ============================================================
-- strategy_evaluation_context — header row per judgement
-- Mutual references: each child table (A–J) holds evaluation_id → here;
-- back-reference columns (technicals_id … news_topics_id) are added via
-- ALTER TABLE after all child tables are created (see bottom of file).
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.strategy_evaluation_context (
    id                          BIGSERIAL       PRIMARY KEY,
    judgement_history_id        BIGINT          NOT NULL UNIQUE
        REFERENCES fin_strategies.judgement_history (id) ON DELETE CASCADE,
    strategy_id                 BIGINT          NOT NULL
        REFERENCES fin_strategies.strategies (id),
    security_id                 BIGINT          NOT NULL
        REFERENCES fin_markets.securities (id),
    snapshot_at                 TIMESTAMPTZ     NOT NULL,
    extra                       JSONB           NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_sec_ctx_judgement
    ON fin_strategies.strategy_evaluation_context (judgement_history_id);
CREATE INDEX IF NOT EXISTS idx_sec_ctx_strategy_sec
    ON fin_strategies.strategy_evaluation_context (strategy_id, security_id, snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_sec_ctx_snapshot_at
    ON fin_strategies.strategy_evaluation_context (snapshot_at DESC);
CREATE INDEX IF NOT EXISTS idx_sec_ctx_security
    ON fin_strategies.strategy_evaluation_context (security_id, snapshot_at DESC);


-- ============================================================
-- A. sec_technicals — price & derived technical signals
-- Base signals read from security_trade_stat_aggregs via trade_stat_id.
-- Derived columns (macd, bollinger bands, pct signals) filled by
-- application using window_coeff for Bollinger band width.
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sec_technicals (
    id                  BIGSERIAL       PRIMARY KEY,
    evaluation_id       BIGINT          NOT NULL UNIQUE
        REFERENCES fin_strategies.strategy_evaluation_context (id) ON DELETE CASCADE,
    trade_stat_id       BIGINT
        REFERENCES fin_markets.security_trade_stat_aggregs (id),
    window_coeff        NUMERIC(4,2)    NOT NULL DEFAULT 2.0,       -- Bollinger σ multiplier

    -- Derived signals (computed from trade_stat_id row by application)
    -- Formula: macd = ema_12 - ema_26
    macd                NUMERIC(20,6),
    -- Formula: macd_hist = macd - macd_signal
    macd_hist           NUMERIC(20,6),
    -- Formula: bollinger_upper = bollinger_mid + window_coeff * bollinger_std
    bollinger_upper     NUMERIC(20,6),
    -- Formula: bollinger_lower = bollinger_mid - window_coeff * bollinger_std
    bollinger_lower     NUMERIC(20,6),
    -- Formula: (price - lower) / (upper - lower)
    bb_pctb             NUMERIC(10,6),
    -- Formula: Simple moving average 3
    sma3                NUMERIC(20,6),
    -- Formula: Simple moving average 5
    sma5                NUMERIC(20,6),
    -- Formula: (price - sma_3) / sma_3
    price_vs_sma3_pct   NUMERIC(10,6),
    -- Formula: (price - sma_5) / sma_5
    price_vs_sma5_pct   NUMERIC(10,6),
    -- Formula: (price - sma_50) / sma_50
    price_vs_sma50_pct  NUMERIC(10,6),
    -- Formula: (price - sma_200) / sma_200
    price_vs_sma200_pct NUMERIC(10,6),
    -- Formula: (price - 52w_low) / (52w_high - 52w_low)
    price_52w_pct       NUMERIC(10,6)
);

CREATE INDEX IF NOT EXISTS idx_sec_technicals_eval
    ON fin_strategies.sec_technicals (evaluation_id);
CREATE INDEX IF NOT EXISTS idx_sec_technicals_trade_stat
    ON fin_strategies.sec_technicals (trade_stat_id);


-- ============================================================
-- B. sec_fundamentals — slow-changing fundamentals snapshot
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sec_fundamentals (
    id                      BIGSERIAL       PRIMARY KEY,
    evaluation_id           BIGINT          NOT NULL UNIQUE
        REFERENCES fin_strategies.strategy_evaluation_context (id) ON DELETE CASCADE,
    security_ext_id         BIGINT
        REFERENCES fin_markets.security_exts (id),

    market_cap_usd          NUMERIC(20,2),
    pe_ratio                NUMERIC(12,4),
    pe_forward              NUMERIC(12,4),
    pb_ratio                NUMERIC(12,4),
    ev_ebitda               NUMERIC(12,4),
    peg_ratio               NUMERIC(12,4),
    ps_ratio                NUMERIC(12,4),
    eps_ttm                 NUMERIC(12,4),
    revenue_ttm             NUMERIC(20,2),
    net_margin              NUMERIC(10,4),
    roe                     NUMERIC(10,4),
    roa                     NUMERIC(10,4),
    debt_to_equity          NUMERIC(10,4),
    current_ratio           NUMERIC(10,4),
    dividend_yield          NUMERIC(10,6),
    short_ratio             NUMERIC(10,4),                      -- days to cover (short interest / avg daily vol)
    insider_pct             NUMERIC(10,4),
    institutional_pct       NUMERIC(10,4),
    analyst_target_price    NUMERIC(12,4),
    analyst_consensus       TEXT,                               -- e.g. 'BUY', 'HOLD', 'SELL'
    earnings_surprise_pct   NUMERIC(10,4),
    beta                    NUMERIC(10,4),                      -- vs benchmark
    fundamental_sentiment   fin_markets.sentiment_level         -- AI-assessed from security_ext_aggregs
);

CREATE INDEX IF NOT EXISTS idx_sec_fundamentals_eval
    ON fin_strategies.sec_fundamentals (evaluation_id);


-- ============================================================
-- C. sec_index_perf — parent index / benchmark performance
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sec_index_perf (
    id                          BIGSERIAL       PRIMARY KEY,
    evaluation_id               BIGINT          NOT NULL UNIQUE
        REFERENCES fin_strategies.strategy_evaluation_context (id) ON DELETE CASCADE,
    index_security_id           BIGINT
        REFERENCES fin_markets.securities (id),
    index_stat_id               BIGINT
        REFERENCES fin_markets.index_stats (id),

    index_price                 NUMERIC(20,6),              -- index level at snapshot
    index_interval_return       NUMERIC(10,6),              -- 1-day index return
    index_weighted_return_5d    NUMERIC(10,6),              -- 5-day cap-weighted return
    index_pct_above_sma_200     NUMERIC(10,4),              -- breadth: % constituents above 200-SMA
    index_avg_pe                NUMERIC(12,4),
    index_volatility_20         NUMERIC(10,6),
    index_sentiment             fin_markets.sentiment_level -- latest AI sentiment on the index
);

CREATE INDEX IF NOT EXISTS idx_sec_index_perf_eval
    ON fin_strategies.sec_index_perf (evaluation_id);


-- ============================================================
-- D. sec_industry_perf — industry / sector aggregate performance
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sec_industry_perf (
    id                          BIGSERIAL       PRIMARY KEY,
    evaluation_id               BIGINT          NOT NULL UNIQUE
        REFERENCES fin_strategies.strategy_evaluation_context (id) ON DELETE CASCADE,

    industry                    TEXT,                       -- GICS sector (e.g. 'TECHNOLOGY')
    industry_peer_count         INTEGER,
    industry_avg_return_1d      NUMERIC(10,6),
    industry_avg_return_5d      NUMERIC(10,6),
    industry_avg_pe             NUMERIC(12,4),
    industry_avg_volatility_20  NUMERIC(10,6),
    industry_sentiment          fin_markets.sentiment_level,
    security_vs_industry_return NUMERIC(10,6)               -- interval_return − industry_avg_return_1d (alpha)
);

CREATE INDEX IF NOT EXISTS idx_sec_industry_perf_eval
    ON fin_strategies.sec_industry_perf (evaluation_id);


-- ============================================================
-- E. sec_options — options market signals on the underlying security
-- All metrics are aggregated across the full option chain of the
-- underlying at snapshot_at.  Put vs call breakdown is provided for
-- every key dimension so the agent can read directional conviction
-- and hedging pressure directly from the underlying's option market.
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sec_options (
    id                          BIGSERIAL       PRIMARY KEY,
    evaluation_id               BIGINT          NOT NULL UNIQUE
        REFERENCES fin_strategies.strategy_evaluation_context (id) ON DELETE CASCADE,
    underlying_security_id      BIGINT
        REFERENCES fin_markets.securities (id),

    -- ── open interest ────────────────────────────────────────
    oi_calls                    BIGINT,                     -- total call open interest
    oi_puts                     BIGINT,                     -- total put open interest
    put_call_oi_ratio           NUMERIC(10,4),              -- oi_puts / oi_calls (>1 = bearish skew)
    oi_calls_change_1d_pct      NUMERIC(10,4),              -- 1-day % change in call OI
    oi_calls_change_3d_pct      NUMERIC(10,4),              -- 3-day % change in call OI
    oi_calls_change_1w_pct      NUMERIC(10,4),              -- 1-week % change in call OI
    oi_puts_change_1d_pct       NUMERIC(10,4),              -- 1-day % change in put OI
    oi_puts_change_3d_pct       NUMERIC(10,4),              -- 3-day % change in put OI
    oi_puts_change_1w_pct       NUMERIC(10,4),              -- 1-week % change in put OI

    -- ── volume ──────────────────────────────────────────────
    volume_calls                BIGINT,
    volume_puts                 BIGINT,
    put_call_volume_ratio       NUMERIC(10,4),              -- volume_puts / volume_calls
    put_call_volume_ratio_1d_chg NUMERIC(10,4),             -- 1-day diff in volume ratio
    put_call_volume_ratio_3d_chg NUMERIC(10,4),             -- 3-day diff in volume ratio
    put_call_volume_ratio_1w_chg NUMERIC(10,4),             -- 1-week diff in volume ratio

    -- ── implied volatility ──────────────────────────────────
    iv_atm                      NUMERIC(10,6),              -- ATM IV blended (annualized)
    iv_atm_1d_chg               NUMERIC(10,6),              -- 1-day ATM IV difference
    iv_atm_3d_chg               NUMERIC(10,6),              -- 3-day ATM IV difference
    iv_atm_1w_chg               NUMERIC(10,6),              -- 1-week ATM IV difference
    iv_calls_atm                NUMERIC(10,6),              -- ATM call IV
    iv_puts_atm                 NUMERIC(10,6),              -- ATM put IV
    iv_skew                     NUMERIC(10,6),              -- 25Δ put IV − 25Δ call IV (>0 = put premium)
    iv_term_1m                  NUMERIC(10,6),              -- ~30-day ATM IV
    iv_term_3m                  NUMERIC(10,6),              -- ~90-day ATM IV
    iv_term_6m                  NUMERIC(10,6),              -- ~180-day ATM IV
    iv_term_structure           TEXT
        CHECK (iv_term_structure IN ('CONTANGO','BACKWARDATION','FLAT', NULL)),

    -- ── greeks (aggregate net across all strikes & expiries) ─
    net_delta_calls             NUMERIC(20,6),              -- sum of call deltas × OI
    net_delta_puts              NUMERIC(20,6),              -- sum of put deltas × OI (negative)
    net_delta                   NUMERIC(20,6),              -- net_delta_calls + net_delta_puts
    gamma_exposure_calls        NUMERIC(20,6),              -- dealer net GEX from calls
    gamma_exposure_puts         NUMERIC(20,6),              -- dealer net GEX from puts
    gamma_exposure              NUMERIC(20,6),              -- total dealer GEX; <0 → vol amplification
    vanna                       NUMERIC(20,6),              -- sensitivity of delta to IV changes
    charm                       NUMERIC(20,6),              -- delta decay (delta sensitivity to time)

    -- ── key price levels derived from options ───────────────
    max_pain                    NUMERIC(20,6),              -- strike where most OI expires worthless
    largest_call_oi_strike      NUMERIC(20,6),              -- strike with highest call OI (resistance)
    largest_put_oi_strike       NUMERIC(20,6),              -- strike with highest put OI (support)

    -- ── overall positioning signal ───────────────────────────
    options_sentiment           fin_markets.sentiment_level -- AI-assessed directional bias from options
);

CREATE INDEX IF NOT EXISTS idx_sec_options_eval
    ON fin_strategies.sec_options (evaluation_id);


-- ============================================================
-- F. sec_futures — futures term structure across standard maturities
-- Periods: front (nearest contract), month (~1M), season (~3M),
--          half_year (~6M), one_year (~12M).
-- Per-period columns follow the pattern: {period}_{metric}.
-- Roll yields measure carry between consecutive contracts (annualised %).
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sec_futures (
    id                      BIGSERIAL       PRIMARY KEY,
    evaluation_id           BIGINT          NOT NULL UNIQUE
        REFERENCES fin_strategies.strategy_evaluation_context (id) ON DELETE CASCADE,
    underlying_security_id  BIGINT
        REFERENCES fin_markets.securities (id),

    -- ── spot reference ──────────────────────────────────────
    spot_price              NUMERIC(20,6),                  -- underlying spot at snapshot_at

    -- ── per-period settlement / last prices ─────────────────
    front_price             NUMERIC(20,6),                  -- nearest active contract
    month_price             NUMERIC(20,6),                  -- ~1-month contract
    season_price            NUMERIC(20,6),                  -- ~3-month (quarterly) contract
    half_year_price         NUMERIC(20,6),                  -- ~6-month contract
    one_year_price          NUMERIC(20,6),                  -- ~12-month contract

    -- ── per-period basis (contract_price − spot) ────────────
    front_basis             NUMERIC(20,6),
    month_basis             NUMERIC(20,6),
    season_basis            NUMERIC(20,6),
    half_year_basis         NUMERIC(20,6),
    one_year_basis          NUMERIC(20,6),

    -- ── per-period annualised basis (%) ─────────────────────
    front_annualized_basis  NUMERIC(10,6),
    month_annualized_basis  NUMERIC(10,6),
    season_annualized_basis NUMERIC(10,6),
    half_year_annualized_basis NUMERIC(10,6),
    one_year_annualized_basis  NUMERIC(10,6),

    -- ── per-period open interest ─────────────────────────────
    front_open_interest     BIGINT,
    month_open_interest     BIGINT,
    season_open_interest    BIGINT,
    half_year_open_interest BIGINT,
    one_year_open_interest  BIGINT,

    -- ── identical contract historical performance ────────────
    -- Price returns of the *same* contract (isolates roll effect)
    front_price_return_1d   NUMERIC(10,6),
    front_price_return_3d   NUMERIC(10,6),
    front_price_return_1w   NUMERIC(10,6),
    
    month_price_return_1d   NUMERIC(10,6),
    month_price_return_3d   NUMERIC(10,6),
    month_price_return_1w   NUMERIC(10,6),

    -- ── identical contract OI history (conviction trends) ────
    -- Note: 1-day replaces previous front_oi_change_pct
    front_oi_change_1d_pct  NUMERIC(10,4),
    front_oi_change_3d_pct  NUMERIC(10,4),
    front_oi_change_1w_pct  NUMERIC(10,4),
    
    month_oi_change_1d_pct  NUMERIC(10,4),
    month_oi_change_3d_pct  NUMERIC(10,4),
    month_oi_change_1w_pct  NUMERIC(10,4),

    -- ── per-period volume ratio (contract vol / avg daily vol)
    front_volume_ratio      NUMERIC(10,4),
    month_volume_ratio      NUMERIC(10,4),
    season_volume_ratio     NUMERIC(10,4),
    half_year_volume_ratio  NUMERIC(10,4),
    one_year_volume_ratio   NUMERIC(10,4),

    -- ── inter-period roll yields (annualised %) ──────────────
    -- Formula: (far_price / near_price - 1) * (365 / days_between)
    roll_yield_spot_to_front      NUMERIC(10,6),
    roll_yield_front_to_month     NUMERIC(10,6),
    roll_yield_month_to_season    NUMERIC(10,6),
    roll_yield_season_to_half     NUMERIC(10,6),
    roll_yield_half_to_year       NUMERIC(10,6),

    -- ── term-structure shape ──────────────────────────────────
    term_structure          TEXT
        CHECK (term_structure IN ('CONTANGO','BACKWARDATION','FLAT', NULL))
);

CREATE INDEX IF NOT EXISTS idx_sec_futures_eval
    ON fin_strategies.sec_futures (evaluation_id);


-- ============================================================
-- G. sec_sector_derivatives — sector-level futures & options
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sec_sector_derivatives (
    id                          BIGSERIAL       PRIMARY KEY,
    evaluation_id               BIGINT          NOT NULL UNIQUE
        REFERENCES fin_strategies.strategy_evaluation_context (id) ON DELETE CASCADE,
    sector_proxy_security_id    BIGINT
        REFERENCES fin_markets.securities (id),

    sector_futures_price        NUMERIC(20,6),
    sector_futures_return_1d    NUMERIC(10,6),
    sector_futures_oi           BIGINT,
    sector_options_put_call     NUMERIC(10,4),
    sector_options_iv           NUMERIC(10,6),
    sector_options_iv_skew      NUMERIC(10,6)
);

CREATE INDEX IF NOT EXISTS idx_sec_sector_deriv_eval
    ON fin_strategies.sec_sector_derivatives (evaluation_id);


-- ============================================================
-- H. sec_news_sentiment — aggregated news sentiment window
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sec_news_sentiment (
    id                      BIGSERIAL       PRIMARY KEY,
    evaluation_id           BIGINT          NOT NULL UNIQUE
        REFERENCES fin_strategies.strategy_evaluation_context (id) ON DELETE CASCADE,
    news_latest_id          BIGINT
        REFERENCES fin_markets.news (id),

    news_lookback_hours     INTEGER         NOT NULL DEFAULT 48,
    news_article_count      INTEGER,
    news_positive_pct       NUMERIC(5,2),                   -- % POSITIVE + VERY_POSITIVE
    news_negative_pct       NUMERIC(5,2),                   -- % NEGATIVE + VERY_NEGATIVE
    news_weighted_sentiment fin_markets.sentiment_level,    -- coverage-weighted modal sentiment
    news_industry_sentiment fin_markets.sentiment_level,    -- aggregated across same-industry news
    news_macro_sentiment    fin_markets.sentiment_level     -- aggregated macro / index news
);

CREATE INDEX IF NOT EXISTS idx_sec_news_sentiment_eval
    ON fin_strategies.sec_news_sentiment (evaluation_id);


-- ============================================================
-- I. sec_macro — macro backdrop at snapshot time
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sec_macro (
    id                  BIGSERIAL       PRIMARY KEY,
    evaluation_id       BIGINT          NOT NULL UNIQUE
        REFERENCES fin_strategies.strategy_evaluation_context (id) ON DELETE CASCADE,

    macro_vix           NUMERIC(10,4),                      -- CBOE VIX level
    macro_vix_1w_change NUMERIC(10,4),                      -- VIX 5-day change (rising = fear)
    macro_yield_10y     NUMERIC(10,6),
    macro_yield_2y      NUMERIC(10,6),
    macro_yield_curve   NUMERIC(10,6),                      -- 10y - 2y spread (inversion = recession signal)
    macro_dxy           NUMERIC(10,4),
    macro_dxy_return_1d NUMERIC(10,6),
    macro_credit_spread NUMERIC(10,6),                      -- IG credit spread proxy (OAS, bps)
    macro_regime        TEXT
        CHECK (macro_regime IN ('RISK_ON','RISK_OFF','NEUTRAL', NULL))
);

CREATE INDEX IF NOT EXISTS idx_sec_macro_eval
    ON fin_strategies.sec_macro (evaluation_id);


-- ============================================================
-- J. sec_news_topics — news topic relevance at evaluation time
-- Links an evaluation snapshot to fin_markets.news_topics nodes
-- that were active / relevant at snapshot_at.
-- One row per (evaluation, topic) pair; topic.path (ltree) allows
-- subtree queries, e.g. all evaluations touching a geopolitical thread.
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sec_news_topics (
    id              BIGSERIAL       PRIMARY KEY,
    evaluation_id   BIGINT          NOT NULL
        REFERENCES fin_strategies.strategy_evaluation_context (id) ON DELETE CASCADE,
    news_topic_id   BIGINT          NOT NULL
        REFERENCES fin_markets.news_topics (id),
    relevance_score NUMERIC(5,4),                           -- 0–1 relevance weight assigned by the agent
    UNIQUE (evaluation_id, news_topic_id)
);

CREATE INDEX IF NOT EXISTS idx_sec_news_topics_eval
    ON fin_strategies.sec_news_topics (evaluation_id);
CREATE INDEX IF NOT EXISTS idx_sec_news_topics_topic
    ON fin_strategies.sec_news_topics (news_topic_id);


-- ============================================================
-- K. sec_intraday — intraday market anomaly signals
-- Maps detected execution patterns (panic, manipulation, etc)
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sec_intraday (
    id                          BIGSERIAL       PRIMARY KEY,
    evaluation_id               BIGINT          NOT NULL UNIQUE
        REFERENCES fin_strategies.strategy_evaluation_context (id) ON DELETE CASCADE,

    -- Source data references
    morning_summary_id          BIGINT
        REFERENCES fin_markets.security_intraday_morning_summary (id),
    afternoon_summary_id        BIGINT
        REFERENCES fin_markets.security_intraday_afternoon_summary (id),

    -- Evaluated Intraday Signals
    is_morning_panic            BOOLEAN,        -- High morning volume with negative gap/momentum
    is_morning_euphoria         BOOLEAN,        -- High morning volume with positive gap/momentum
    is_tail_suppression         BOOLEAN,        -- Abnormal afternoon volume with negative closing return
    is_tail_rally               BOOLEAN,        -- Abnormal afternoon volume with positive closing return
    is_close_manipulated        BOOLEAN,        -- Close diverges significantly from afternoon VWAP
    
    intraday_momentum_score     NUMERIC(10,6)   -- Composite score of morning/afternoon flow continuity
);

CREATE INDEX IF NOT EXISTS idx_sec_intraday_eval
    ON fin_strategies.sec_intraday (evaluation_id);


-- ============================================================
-- L. sec_historical_extremes — long-term historical extremes
-- Maps 1, 2, 5, and 10 year price extremes and trends
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sec_historical_extremes (
    id                          BIGSERIAL       PRIMARY KEY,
    evaluation_id               BIGINT          NOT NULL UNIQUE
        REFERENCES fin_strategies.strategy_evaluation_context (id) ON DELETE CASCADE,

    -- 1 Year
    peak_1y                     NUMERIC(20,6),
    trough_1y                   NUMERIC(20,6),
    current_vs_peak_1y_pct      NUMERIC(10,4),
    current_vs_trough_1y_pct    NUMERIC(10,4),
    biggest_sma3_1y             NUMERIC(20,6),
    biggest_sma7_1y             NUMERIC(20,6),
    sma200_trend_1y             TEXT CHECK (sma200_trend_1y IN ('RISING','FALLING','FLAT', NULL)),

    -- 2 Year
    peak_2y                     NUMERIC(20,6),
    trough_2y                   NUMERIC(20,6),
    current_vs_peak_2y_pct      NUMERIC(10,4),
    current_vs_trough_2y_pct    NUMERIC(10,4),
    biggest_sma3_2y             NUMERIC(20,6),
    biggest_sma7_2y             NUMERIC(20,6),
    sma200_trend_2y             TEXT CHECK (sma200_trend_2y IN ('RISING','FALLING','FLAT', NULL)),

    -- 5 Year
    peak_5y                     NUMERIC(20,6),
    trough_5y                   NUMERIC(20,6),
    current_vs_peak_5y_pct      NUMERIC(10,4),
    current_vs_trough_5y_pct    NUMERIC(10,4),
    biggest_sma3_5y             NUMERIC(20,6),
    biggest_sma7_5y             NUMERIC(20,6),
    sma200_trend_5y             TEXT CHECK (sma200_trend_5y IN ('RISING','FALLING','FLAT', NULL)),

    -- 10 Year
    peak_10y                    NUMERIC(20,6),
    trough_10y                  NUMERIC(20,6),
    current_vs_peak_10y_pct     NUMERIC(10,4),
    current_vs_trough_10y_pct   NUMERIC(10,4),
    biggest_sma3_10y            NUMERIC(20,6),
    biggest_sma7_10y            NUMERIC(20,6),
    sma200_trend_10y            TEXT CHECK (sma200_trend_10y IN ('RISING','FALLING','FLAT', NULL))
);

CREATE INDEX IF NOT EXISTS idx_sec_hist_extremes_eval
    ON fin_strategies.sec_historical_extremes (evaluation_id);


-- ============================================================
-- M2. sec_digested_news — tracks how/whether news has been absorbed by price action
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sec_digested_news (
    id                      BIGSERIAL       PRIMARY KEY,
    evaluation_id           BIGINT          NOT NULL UNIQUE
        REFERENCES fin_strategies.strategy_evaluation_context (id) ON DELETE CASCADE,
    news_ext_id             BIGINT          REFERENCES fin_markets.news_exts (id),
    is_digested             BOOLEAN,
    digest_lag_days         SMALLINT,
    extra                   JSONB           NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_sec_digested_news_eval ON fin_strategies.sec_digested_news (evaluation_id);


-- ============================================================
-- N. sec_weekly_trade_stats — rolling 1-week trading statistics
-- Aggregated from security_trade_stat_aggregs over the trailing
-- 5 trading days.  Captures price trend, volume conviction, and
-- intra-week volatility to complement intraday and technical dims.
-- Includes sub-windows for 1, 2, and 3-day history to capture recent momentum shifts.
-- It can also serve as a source for if news has already been digested into price action
-- e.g. large 1-day gap with high volume but no follow-through in 3-day window may indicate news overreaction
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sec_weekly_trade_stats (
    id                      BIGSERIAL       PRIMARY KEY,
    evaluation_id           BIGINT          NOT NULL UNIQUE
        REFERENCES fin_strategies.strategy_evaluation_context (id) ON DELETE CASCADE,

    -- Window metadata
    week_start              DATE,                           -- first trading day of window
    week_end                DATE,                           -- last trading day (≤ snapshot_at)
    trading_days            INTEGER,                        -- actual sessions in window (usually 5)

    -- OHLCV aggregates
    week_open               NUMERIC(20,6),                  -- price at start of week_start session
    week_high               NUMERIC(20,6),
    week_low                NUMERIC(20,6),
    week_close              NUMERIC(20,6),                  -- price at end of week_end session
    week_volume             BIGINT,                         -- cumulative volume

    -- Return metrics
    week_return             NUMERIC(10,6),                  -- (week_close - week_open) / week_open
    week_high_return        NUMERIC(10,6),                  -- (week_high - week_open) / week_open
    week_low_return         NUMERIC(10,6),                  -- (week_low  - week_open) / week_open

    -- Volume analysis
    avg_daily_volume_4w     BIGINT,                         -- 4-week avg daily vol baseline
    week_volume_ratio       NUMERIC(10,4),                  -- week_volume / (trading_days * avg_daily_volume_4w)
    volume_trend            TEXT
        CHECK (volume_trend IN ('INCREASING','DECREASING','FLAT', NULL)),

    -- Intra-week volatility
    week_true_range         NUMERIC(20,6),                  -- week_high - week_low
    week_atr_ratio          NUMERIC(10,6),                  -- week_true_range / week_close (normalised)

    -- Daily return distribution within the week
    positive_days           INTEGER,                        -- # sessions with positive close-to-close return
    negative_days           INTEGER,                        -- # sessions with negative close-to-close return
    max_up_day_return       NUMERIC(10,6),                  -- largest single-day up move
    max_down_day_return     NUMERIC(10,6),                  -- largest single-day down move (signed, negative)

    -- Price-vs-MA context at week end
    price_vs_sma20_pct      NUMERIC(10,6),                  -- (week_close - sma_20) / sma_20
    price_vs_sma50_pct      NUMERIC(10,6),                  -- (week_close - sma_50) / sma_50

    -- Overall weekly momentum signal
    weekly_momentum         fin_markets.sentiment_level,    -- AI-assessed weekly direction

    -- ── 1-day history (yesterday) ───────────────────────────
    d1_open                 NUMERIC(20,6),
    d1_high                 NUMERIC(20,6),
    d1_low                  NUMERIC(20,6),
    d1_close                NUMERIC(20,6),
    d1_volume               BIGINT,
    d1_return               NUMERIC(10,6),                  -- (d1_close - d1_open) / d1_open
    d1_volume_ratio         NUMERIC(10,4),                  -- d1_volume / avg_daily_volume_4w
    d1_true_range           NUMERIC(20,6),                  -- d1_high - d1_low
    d1_gap_pct              NUMERIC(10,6),                  -- (d1_open - prior_close) / prior_close

    -- ── 2-day history (rolling 2 sessions) ──────────────────
    d2_open                 NUMERIC(20,6),                  -- open of 2 sessions ago
    d2_high                 NUMERIC(20,6),                  -- high over last 2 sessions
    d2_low                  NUMERIC(20,6),                  -- low over last 2 sessions
    d2_close                NUMERIC(20,6),                  -- close of 2 sessions ago
    d2_volume               BIGINT,                         -- cumulative volume over 2 sessions
    d2_return               NUMERIC(10,6),                  -- (d1_close - d2_open) / d2_open
    d2_volume_ratio         NUMERIC(10,4),                  -- d2_volume / (2 * avg_daily_volume_4w)
    d2_true_range           NUMERIC(20,6),                  -- range high - range low over 2 sessions

    -- ── 3-day history (rolling 3 sessions) ──────────────────
    d3_open                 NUMERIC(20,6),                  -- open of 3 sessions ago
    d3_high                 NUMERIC(20,6),                  -- high over last 3 sessions
    d3_low                  NUMERIC(20,6),                  -- low over last 3 sessions
    d3_close                NUMERIC(20,6),                  -- close of 3 sessions ago
    d3_volume               BIGINT,                         -- cumulative volume over 3 sessions
    d3_return               NUMERIC(10,6),                  -- (d1_close - d3_open) / d3_open
    d3_volume_ratio         NUMERIC(10,4),                  -- d3_volume / (3 * avg_daily_volume_4w)
    d3_true_range           NUMERIC(20,6)                   -- range high - range low over 3 sessions
);

CREATE INDEX IF NOT EXISTS idx_sec_weekly_trade_stats_eval
    ON fin_strategies.sec_weekly_trade_stats (evaluation_id);


-- ============================================================
-- Back-references: add child-table id columns to the parent.
-- Done here (after child CREATE TABLE) to avoid forward-reference errors.
-- All nullable — a domain row may not exist for every evaluation.
-- ============================================================
ALTER TABLE fin_strategies.strategy_evaluation_context
    ADD COLUMN IF NOT EXISTS technicals_id          BIGINT  REFERENCES fin_strategies.sec_technicals (id),
    ADD COLUMN IF NOT EXISTS fundamentals_id        BIGINT  REFERENCES fin_strategies.sec_fundamentals (id),
    ADD COLUMN IF NOT EXISTS index_perf_id          BIGINT  REFERENCES fin_strategies.sec_index_perf (id),
    ADD COLUMN IF NOT EXISTS industry_perf_id       BIGINT  REFERENCES fin_strategies.sec_industry_perf (id),
    ADD COLUMN IF NOT EXISTS options_id             BIGINT  REFERENCES fin_strategies.sec_options (id),
    ADD COLUMN IF NOT EXISTS futures_id             BIGINT  REFERENCES fin_strategies.sec_futures (id),
    ADD COLUMN IF NOT EXISTS sector_derivatives_id  BIGINT  REFERENCES fin_strategies.sec_sector_derivatives (id),
    ADD COLUMN IF NOT EXISTS news_sentiment_id      BIGINT  REFERENCES fin_strategies.sec_news_sentiment (id),
    ADD COLUMN IF NOT EXISTS macro_id               BIGINT  REFERENCES fin_strategies.sec_macro (id),
    ADD COLUMN IF NOT EXISTS news_topics_id         BIGINT  REFERENCES fin_strategies.sec_news_topics (id),
    ADD COLUMN IF NOT EXISTS intraday_id            BIGINT  REFERENCES fin_strategies.sec_intraday (id),
    ADD COLUMN IF NOT EXISTS historical_extremes_id BIGINT  REFERENCES fin_strategies.sec_historical_extremes (id),
    ADD COLUMN IF NOT EXISTS digested_news_id       BIGINT  REFERENCES fin_strategies.sec_digested_news (id),
    ADD COLUMN IF NOT EXISTS weekly_trade_stats_id  BIGINT  REFERENCES fin_strategies.sec_weekly_trade_stats (id);
