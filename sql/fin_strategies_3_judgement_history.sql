CREATE SCHEMA IF NOT EXISTS fin_strategies;

-- strategies must exist before judgement_history references it;
-- fin_strategies_2_dims.sql also creates this table (IF NOT EXISTS = no-op if already exists).
CREATE TABLE IF NOT EXISTS fin_strategies.strategies (
    id              BIGSERIAL       PRIMARY KEY,
    name            TEXT            NOT NULL UNIQUE,
    version         TEXT            NOT NULL DEFAULT '1.0',
    description     TEXT,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    config          JSONB           NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fin_strategies.judgement_history (
    id              BIGSERIAL PRIMARY KEY,
    strategy_id     BIGINT      REFERENCES fin_strategies.strategies (id),
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    security_id             BIGINT      NOT NULL
        REFERENCES fin_markets.securities (id) ON DELETE CASCADE,           -- The security being benchmarked

    rationale       TEXT,                                   -- Optional explanation for the judgement
    extra           JSONB,                                  -- Optional additional structured data about the judgement

    -- --------------------------------------------------------
    -- Per-horizon outlook: sentiment + confidence
    -- Each horizon captures the agent's directional view and
    -- conviction level for that forward-looking time window.
    -- --------------------------------------------------------

    -- Next trading day (~1 day)
    next_day_sentiment      fin_strategies.sentiment_level,
    next_day_confidence     fin_strategies.confidence_level,

    -- One week (7 calendar days)
    one_week_sentiment      fin_strategies.sentiment_level,
    one_week_confidence     fin_strategies.confidence_level,

    -- One month (30 calendar days)
    one_month_sentiment     fin_strategies.sentiment_level,
    one_month_confidence    fin_strategies.confidence_level,

    -- One quarter / season (90 calendar days)
    one_quarter_sentiment   fin_strategies.sentiment_level,
    one_quarter_confidence  fin_strategies.confidence_level,

    -- Half year (180 calendar days)
    half_year_sentiment     fin_strategies.sentiment_level,
    half_year_confidence    fin_strategies.confidence_level,

    -- One year (360 calendar days)
    one_year_sentiment      fin_strategies.sentiment_level,
    one_year_confidence     fin_strategies.confidence_level
);

-- ============================================================
-- judgement_history_intraday
-- Extracts intraday / mid-day specific manipulation estimates
-- Linked 1:1 to the main judgement history for models.
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.judgement_history_intraday (
    id                          BIGSERIAL   PRIMARY KEY,
    judgement_history_id        BIGINT      NOT NULL UNIQUE
        REFERENCES fin_strategies.judgement_history (id) ON DELETE CASCADE,

    -- Intraday / Afternoon Estimates (Evaluated mid-day)
    morning_trend_strength      NUMERIC(10,6),  -- Directional strength of the morning move
    morning_reversal_risk       NUMERIC(5,4),   -- Probability (0-1) of afternoon reversing the morning trend

    est_afternoon_direction     INTEGER,        -- Expected market drift: 1 (bull), -1 (bear), 0 (chop)
    est_afternoon_volatility    NUMERIC(10,6),  -- Expected magnitude of price swings in the afternoon
    est_tail_manipulation       BOOLEAN,        -- True if we predict abnormal volume block / MOC manipulation

    morning_support_level       NUMERIC(20,6),  -- Morning low or strong consolidated VWAP support
    morning_resistance_level    NUMERIC(20,6)   -- Morning high or strong rejection level
);

CREATE INDEX IF NOT EXISTS idx_judgement_intraday_history_id
    ON fin_strategies.judgement_history_intraday (judgement_history_id);

-- ============================================================
-- judgement_benchmark
-- Records the actual market performance of a specific security
-- over each forward-looking horizon, allowing back-testing and
-- accuracy scoring against a corresponding judgement_history row.
--
-- return columns store simple price return (decimal):
--   e.g. 0.035 = +3.5%,  -0.02 = -2.0%
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.judgement_benchmark (
    id                      BIGSERIAL   PRIMARY KEY,
    judgement_history_id    BIGINT      NOT NULL
        REFERENCES fin_strategies.judgement_history (id) ON DELETE CASCADE,
    security_id             BIGINT      NOT NULL
        REFERENCES fin_markets.securities (id) ON DELETE CASCADE,           -- The security being benchmarked

    reference_price         NUMERIC(18, 6) NOT NULL,        -- Security price at the time of the judgement
    reference_timestamp     TIMESTAMPTZ NOT NULL,           -- Copied from judgement_history.timestamp for fast range queries

    -- --------------------------------------------------------
    -- Actual market returns per horizon (NULL until the period elapses)
    -- --------------------------------------------------------

    -- Next trading day (~1 day)
    next_day_price          NUMERIC(18, 6),
    next_day_return         NUMERIC(10, 6),                 -- (next_day_price - reference_price) / reference_price
    next_day_sentiment      fin_strategies.sentiment_level,  -- mapped via sentiment_scale_calibration ('1d')

    -- One week (7 calendar days)
    one_week_price          NUMERIC(18, 6),
    one_week_return         NUMERIC(10, 6),
    one_week_sentiment      fin_strategies.sentiment_level,  -- mapped via sentiment_scale_calibration ('1w')

    -- One month (30 calendar days)
    one_month_price         NUMERIC(18, 6),
    one_month_return        NUMERIC(10, 6),
    one_month_sentiment     fin_strategies.sentiment_level,  -- mapped via sentiment_scale_calibration ('1m')

    -- One quarter / season (90 calendar days)
    one_quarter_price       NUMERIC(18, 6),
    one_quarter_return      NUMERIC(10, 6),
    one_quarter_sentiment   fin_strategies.sentiment_level,  -- mapped via sentiment_scale_calibration ('3m')

    -- Half year (180 calendar days)
    half_year_price         NUMERIC(18, 6),
    half_year_return        NUMERIC(10, 6),
    half_year_sentiment     fin_strategies.sentiment_level,  -- mapped via sentiment_scale_calibration ('6m')

    -- One year (360 calendar days)
    one_year_price          NUMERIC(18, 6),
    one_year_return         NUMERIC(10, 6),
    one_year_sentiment      fin_strategies.sentiment_level,  -- mapped via sentiment_scale_calibration ('1y')

    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_judgement_benchmark_history_id
    ON fin_strategies.judgement_benchmark (judgement_history_id);

CREATE INDEX IF NOT EXISTS idx_judgement_benchmark_security_ts
    ON fin_strategies.judgement_benchmark (security_id, reference_timestamp DESC);