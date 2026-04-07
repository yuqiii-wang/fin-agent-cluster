
CREATE SCHEMA IF NOT EXISTS fin_markets;

-- ============================================================
-- Base — shared meta columns inherited by all tables below.
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.basics (
    id              BIGSERIAL       PRIMARY KEY,
    currency        TEXT            CHECK (currency IS NULL OR fin_markets.is_enum('currency', currency)),  -- currency for the flow value (e.g. USD), N/A for index, etc
    extra           JSONB           NOT NULL DEFAULT '{}',
    published_at    TIMESTAMPTZ     NOT NULL,             -- The timestamp when the data is effective (e.g. trade_date for OHLCV, report_date for fundamentals)
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);






-- ============================================================
-- security_trade_stat_aggregs — base technical indicators per OHLCV bar
-- Canonical source-of-truth for all pre-computed market signals.
-- Derived signals (MACD, Bollinger %B, price-vs-SMA) live in
-- fin_strategies.strategy_technical_signals, computed from these.
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.security_trade_stat_aggregs (
    security_id     BIGINT          NOT NULL REFERENCES fin_markets.securities (id),

    -- Price
    price           NUMERIC(20,6),                           -- close price at snapshot
    interval_return NUMERIC(10,6),                           -- (close - prev_close) / prev_close
    
    -- Historical Price Action (Lags & Streaks)
    return_1d_lag   NUMERIC(10,6),                           -- Yesterday's return
    return_2d_lag   NUMERIC(10,6),                           -- Return 2 days ago
    return_3d_lag   NUMERIC(10,6),                           -- Return 3 days ago
    consecutive_up_days SMALLINT,                            -- Number of consecutive positive return days (rally)
    consecutive_down_days SMALLINT,                          -- Number of consecutive negative return days (drop)

    -- Simple moving averages
    sma_3           NUMERIC(20,6),
    sma_7           NUMERIC(20,6),
    sma_10          NUMERIC(20,6),
    sma_20          NUMERIC(20,6),
    sma_50          NUMERIC(20,6),
    sma_200         NUMERIC(20,6),

    -- Exponential moving averages
    ema_12          NUMERIC(20,6),
    ema_26          NUMERIC(20,6),

    -- MACD base components
    macd_signal     NUMERIC(20,6),                           -- 9-period EMA of (ema_12 - ema_26)
    macd_hist       NUMERIC(20,6)                            -- (ema_12 - ema_26) - macd_signal
        GENERATED ALWAYS AS (ema_12 - ema_26 - macd_signal) STORED,

    -- Momentum / oscillators
    rsi_6           NUMERIC(10,4),
    rsi_14          NUMERIC(10,4),
    stoch_k         NUMERIC(10,4),                           -- stochastic %K (14,3,3)
    stoch_d         NUMERIC(10,4),                           -- stochastic %D

    -- Trend
    adx_14          NUMERIC(10,4),                           -- average directional index

    -- Volatility
    atr_14          NUMERIC(20,6),                           -- average true range (14)
    bollinger_mid   NUMERIC(20,6)                            -- Bollinger middle = sma_20
        GENERATED ALWAYS AS (sma_20) STORED,
    bollinger_std   NUMERIC(20,6),                           -- 20-day price std dev (raw; band width = coeff * std)
    volatility_20d  NUMERIC(10,6),                           -- 20-day realized vol (annualized)
    volatility_60d  NUMERIC(10,6),                           -- 60-day realized vol

    -- Volume
    volume_ratio    NUMERIC(10,4),                           -- today vol / 20d avg vol
    obv             BIGINT,                                  -- on-balance volume

    -- Misc tape / chart signals
    psar            NUMERIC(20,6),                           -- parabolic SAR
    ichimoku_tenkan NUMERIC(20,6),                           -- conversion line (9)
    ichimoku_kijun  NUMERIC(20,6),                           -- base line (26)
    price_52w_high  NUMERIC(20,6),                           -- 52-week high
    price_52w_low   NUMERIC(20,6),                           -- 52-week low

    UNIQUE (security_id, published_at),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);

-- Primary access: "latest technical indicators for security X"
CREATE INDEX IF NOT EXISTS idx_trade_stat_aggregs_sec_date ON fin_markets.security_trade_stat_aggregs (security_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_trade_stat_aggregs_created  ON fin_markets.security_trade_stat_aggregs (created_at DESC);



CREATE TABLE IF NOT EXISTS fin_markets.security_intraday_morning_summary (
    security_id             BIGINT          NOT NULL REFERENCES fin_markets.securities (id),

    -- Price Action
    open_price              NUMERIC(20,6),                           -- Day's open price
    morning_high            NUMERIC(20,6),                           -- Highest price achieved in morning session
    morning_low             NUMERIC(20,6),                           -- Lowest price in morning session
    morning_close           NUMERIC(20,6),                           -- Price at the end of the morning session
    gap_percent             NUMERIC(10,6),                           -- (open - prior_close) / prior_close. Detects overnight news gaps.

    -- Historical Gap Action
    gap_percent_1d_lag      NUMERIC(10,6),                           -- Yesterday's morning gap
    gap_percent_2d_lag      NUMERIC(10,6),                           -- Morning gap 2 days ago
    gap_percent_3d_lag      NUMERIC(10,6),                           -- Morning gap 3 days ago

    -- Volume & Flow
    morning_volume          NUMERIC(25,6),                           -- Total volume traded during the morning
    morning_vwap            NUMERIC(20,6),                           -- Volume Weighted Average Price for the morning
    open_30m_vol_ratio      NUMERIC(10,4),                           -- Open 30 min vol / historical avg morning vol. Detects panic/euphoria at open.

    -- Patterns & Implications
    morning_momentum        NUMERIC(10,6)                            -- Internal momentum: (morning_close - open_price) / open_price
        GENERATED ALWAYS AS (
            CASE WHEN open_price > 0 THEN (morning_close - open_price) / open_price ELSE NULL END
        ) STORED,

    UNIQUE (security_id, published_at),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);
CREATE INDEX IF NOT EXISTS idx_intraday_morning_sec_date ON fin_markets.security_intraday_morning_summary (security_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_intraday_morning_created  ON fin_markets.security_intraday_morning_summary (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_intraday_morning_vol_ratio ON fin_markets.security_intraday_morning_summary (open_30m_vol_ratio DESC, published_at DESC);


CREATE TABLE IF NOT EXISTS fin_markets.security_intraday_afternoon_summary (
    security_id             BIGINT          NOT NULL REFERENCES fin_markets.securities (id),

    -- Price Action
    afternoon_open          NUMERIC(20,6),                           -- Price at the start of afternoon session
    afternoon_high          NUMERIC(20,6),                           -- Highest price in afternoon session
    afternoon_low           NUMERIC(20,6),                           -- Lowest price in afternoon session
    close_price             NUMERIC(20,6),                           -- Official closing price

    -- Volume & Flow
    afternoon_volume        NUMERIC(25,6),                           -- Total volume traded during the afternoon
    afternoon_vwap          NUMERIC(20,6),                           -- VWAP for the afternoon

    -- Tail/Closing Features (Manipulation / MOC Imbalances)
    tail_30m_vol_ratio      NUMERIC(10,4),                           -- Last 30 min vol / historical avg afternoon vol. Detects rush at the end.
    tail_30m_return         NUMERIC(10,6),                           -- Return in the last 30 minutes. Combined with vol ratio to detect shooting/suppressing.

    -- Historical Tail Behavior (Lags)
    tail_30m_return_1d_lag  NUMERIC(10,6),                           -- Tail return yesterday
    tail_30m_return_2d_lag  NUMERIC(10,6),                           -- Tail return 2 days ago
    tail_30m_return_3d_lag  NUMERIC(10,6),                           -- Tail return 3 days ago

    -- Patterns & Implications
    afternoon_momentum      NUMERIC(10,6)                            -- Internal momentum: (close_price - afternoon_open) / afternoon_open
        GENERATED ALWAYS AS (
            CASE WHEN afternoon_open > 0 THEN (close_price - afternoon_open) / afternoon_open ELSE NULL END
        ) STORED,
    close_vs_vwap           NUMERIC(10,6)                            -- Spread between closing price and afternoon VWAP. Detects manipulation off the averages.
        GENERATED ALWAYS AS (
            CASE WHEN afternoon_vwap > 0 THEN (close_price - afternoon_vwap) / afternoon_vwap ELSE NULL END
        ) STORED,

    UNIQUE (security_id, published_at),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);
CREATE INDEX IF NOT EXISTS idx_intraday_afternoon_sec_date ON fin_markets.security_intraday_afternoon_summary (security_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_intraday_afternoon_created  ON fin_markets.security_intraday_afternoon_summary (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_intraday_afternoon_tail_vol ON fin_markets.security_intraday_afternoon_summary (tail_30m_vol_ratio DESC, published_at DESC);

-- ============================================================
-- security_exts — slow-changing fundamentals snapshot per security/date (source data)
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.security_exts (
    security_id         BIGINT          NOT NULL REFERENCES fin_markets.securities (id),
    news_id             BIGINT          REFERENCES fin_markets.news (id),               -- related news impacting the security on that date
    price               NUMERIC(20,6),                                                  -- market price at snapshot (from profile/quote)
    market_cap_usd      NUMERIC(20,2),                                                  -- latest market cap
    pe_ratio            NUMERIC(12,4),
    pb_ratio            NUMERIC(12,4),
    net_margin          NUMERIC(10,4),
    eps_ttm             NUMERIC(12,4),
    revenue_ttm         NUMERIC(20,2),
    debt_to_equity      NUMERIC(10,4),
    dividend_yield      NUMERIC(10,6),
    dividend_rate       NUMERIC(12,4),
    dividend_frequency  TEXT            CHECK (dividend_frequency IS NULL OR fin_markets.is_enum('dividend_frequency', dividend_frequency)),
    UNIQUE (security_id, published_at),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);

CREATE INDEX IF NOT EXISTS idx_security_exts_sec_date ON fin_markets.security_exts (security_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_security_exts_created  ON fin_markets.security_exts (created_at DESC);

-- ============================================================
-- security_ext_aggregs — computed metrics derived from security_exts
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.security_ext_aggregs (
    security_ext_id     BIGINT          NOT NULL REFERENCES fin_markets.security_exts (id),
    sentiment_level     fin_markets.sentiment_level,    -- AI-driven analyst sentiment based on recent news & fundamentals
    beta                NUMERIC(10,4),                  -- computed from price history vs benchmark

    UNIQUE (security_ext_id),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);

CREATE INDEX IF NOT EXISTS idx_security_ext_aggregs_ext_id ON fin_markets.security_ext_aggregs (security_ext_id);
CREATE INDEX IF NOT EXISTS idx_security_ext_aggregs_created ON fin_markets.security_ext_aggregs (created_at DESC);

-- ============================================================
-- Index Dynamic Exts — index constituents, weights, and key stats snapshots
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.index_stats (
    index_id        BIGINT      NOT NULL REFERENCES fin_markets.indexes (id),
    base_value      NUMERIC(20,6),                           -- base level (e.g. 100)
    news_id  BIGINT    REFERENCES fin_markets.news (id),   -- related news impacting the security on that date
    UNIQUE (index_id, published_at),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);

CREATE INDEX IF NOT EXISTS idx_index_stats_idx_date  ON fin_markets.index_stats (index_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_index_stats_created   ON fin_markets.index_stats (created_at DESC);


-- ============================================================
-- index_stat_aggregs — breadth & aggregate stats for an index snapshot
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.index_stat_aggregs (
    index_stat_id        BIGINT      NOT NULL REFERENCES fin_markets.index_stats (id),
    weighted_return     NUMERIC(10,6),                       -- cap-weighted return
    
    -- Historical Returns (Lags & Streaks)
    weighted_return_1d_lag NUMERIC(10,6),                    -- Index return yesterday
    weighted_return_2d_lag NUMERIC(10,6),                    -- Index return 2 days ago
    weighted_return_3d_lag NUMERIC(10,6),                    -- Index return 3 days ago
    consecutive_up_days    SMALLINT,                         -- Number of consecutive positive index returns (rally)
    consecutive_down_days  SMALLINT,                         -- Number of consecutive negative index returns (drop)

    pct_above_sma_200   NUMERIC(10,4),
    avg_pe              NUMERIC(12,4),
    index_volatility_20 NUMERIC(10,6),

    UNIQUE (index_stat_id),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);

CREATE INDEX IF NOT EXISTS idx_index_stat_aggregs_created ON fin_markets.index_stat_aggregs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_index_stat_aggregs_index_stat_id ON fin_markets.index_stat_aggregs (index_stat_id);


-- ============================================================
-- news_exts — AI-generated impact per article
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.news_exts (
    news_id  BIGINT    REFERENCES fin_markets.news (id),   -- related news impacting the security on that date
    sentiment_level    fin_markets.sentiment_level,                -- AI-assessed market impact
    summary         TEXT,                                    -- AI or editorial abstract

    -- publicity
    news_coverage  TEXT CHECK (news_coverage IS NULL OR fin_markets.is_enum('news_coverage', news_coverage)),  -- breadth of coverage across media and social platforms

    UNIQUE (news_id) ,
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);

CREATE INDEX IF NOT EXISTS idx_news_exts_created          ON fin_markets.news_exts (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_exts_news_id ON fin_markets.news_exts (news_id);
-- Sentiment stream: "all very-negative articles in the last 7 days"
CREATE INDEX IF NOT EXISTS idx_news_exts_sentiment     ON fin_markets.news_exts (sentiment_level, published_at DESC);
-- Full-text search vector embedding on summary
CREATE INDEX IF NOT EXISTS idx_news_exts_summary_fts   ON fin_markets.news_exts USING GIN (to_tsvector('english', COALESCE(summary, '')));


-- ============================================================
-- news_topics — hierarchical topic classification tree (Y-axis)
-- Represents the topic taxonomy that news articles are mapped onto.
-- Combined with news.published_at (X-axis) and the
-- news_topics bridge, this forms the (time × topic) grid
-- where each article is a node.
--
-- Tree is stored as an adjacency list (parent_id) plus a PostgreSQL
-- ltree materialized path for efficient subtree and ancestor queries
-- without recursive CTEs.
--
-- Example paths:
-- Iran_US_War_2026.Navy_Assembly
-- Iran_US_War_2026.Hormuz.Ship_No_Issuance
-- Iran_US_War_2026.Hormuz.Ship_Attack
-- Iran_US_War_2026.Assassination.Khamenei_Death
-- ============================================================
CREATE EXTENSION IF NOT EXISTS ltree;

CREATE TABLE IF NOT EXISTS fin_markets.news_topics (
    id              BIGSERIAL       PRIMARY KEY,
    parent_id       BIGINT          REFERENCES fin_markets.news_topics (id) ON DELETE RESTRICT,
    name            TEXT            NOT NULL,
    slug            TEXT            NOT NULL,
    path            ltree           NOT NULL,
    level           SMALLINT        NOT NULL DEFAULT 0,       -- 0 = root, 1 = L1, 2 = L2, …
    description     TEXT,
    num_data_sources INT             NOT NULL DEFAULT 0,       -- number of news articles mapped to this topic (including descendants)
    extra           JSONB           NOT NULL DEFAULT '{}',
    UNIQUE (parent_id, slug),
    UNIQUE (path)
) INHERITS (fin_markets.basics);

-- Subtree / ancestor queries: path <@ 'macro.central_bank'  →  all descendants
CREATE INDEX IF NOT EXISTS idx_news_topics_path     ON fin_markets.news_topics USING GIST (path);
-- Parent navigation (building breadcrumbs / tree UI)
CREATE INDEX IF NOT EXISTS idx_news_topics_parent   ON fin_markets.news_topics (parent_id)  WHERE parent_id IS NOT NULL;
-- Level-filtered listing: "show all L1 topics"
CREATE INDEX IF NOT EXISTS idx_news_topics_level    ON fin_markets.news_topics (level);

-- ============================================================
-- macro_economics — macroeconomic indicator releases
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.macro_economics (
    news_ext_id  BIGINT    REFERENCES fin_markets.news_exts (id),   -- related news impacting the security on that date
    category                 TEXT            CHECK (category IS NULL OR fin_markets.is_enum('news_category', category)),
    industry                 TEXT            CHECK (industry IS NULL OR fin_markets.is_enum('industry', industry)),   -- GICS sector slice (NULL = region-level aggregate row)
    region                   TEXT            NOT NULL CHECK (fin_markets.is_enum('region', region)),
    actual                   NUMERIC(20,6),
    sentiment_level          fin_markets.sentiment_level,         -- AI-driven aggregate sentiment for the industry
    UNIQUE (category, region, published_at),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);

CREATE INDEX IF NOT EXISTS idx_macro_ind_region_date ON fin_markets.macro_economics (category, region, published_at DESC);
-- Time-only scan: "all macro releases in the last 30 days"
CREATE INDEX IF NOT EXISTS idx_macro_ind_date        ON fin_markets.macro_economics (published_at DESC);


-- ============================================================
-- industry_stats an industry-level performance per region per date
-- Describes how each GICS sector is performing within the parent region snapshot.
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.industry_stats (
    industry             TEXT            CHECK (industry IS NULL OR fin_markets.is_enum('industry', industry)),   -- GICS sector slice (NULL = region-level aggregate row)
    region               TEXT            CHECK (region IS NULL OR fin_markets.is_enum('region', region)),         -- denormalised region for direct time-series queries
    volume               NUMERIC(25,6),                      -- total traded volume for the industry on that date
    relative_flow_pct    NUMERIC(10,6),                      -- net flow vs. cross-industry average (positive = above-avg inflow)
    breadth_pct          NUMERIC(10,4),                      -- % of constituents with positive flow (>0.5 = broad inflow, <0.5 = broad outflow)
    sentiment_level     fin_markets.sentiment_level,         -- AI-driven aggregate sentiment for the industry
    UNIQUE (industry, region, published_at),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);

-- Primary access: "how did tech perform in the US last week?"
CREATE INDEX IF NOT EXISTS idx_industry_stats_ind_region_date ON fin_markets.industry_stats (industry, region, published_at DESC) WHERE industry IS NOT NULL AND region IS NOT NULL;
-- Region time-series: "all sectors in US this month"
CREATE INDEX IF NOT EXISTS idx_industry_stats_region_date     ON fin_markets.industry_stats (region, published_at DESC) WHERE region IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_industry_stats_created         ON fin_markets.industry_stats (created_at DESC);

CREATE TABLE IF NOT EXISTS fin_markets.industry_stat_aggregs (
    industry_stat_id    BIGINT      NOT NULL REFERENCES fin_markets.industry_stats (id) ON DELETE CASCADE,
    avg_return          NUMERIC(10,6),                       -- cap-weighted avg return of constituents
    
    -- Historical Returns (Lags & Streaks)
    avg_return_1d_lag   NUMERIC(10,6),                       -- Industry return yesterday
    avg_return_2d_lag   NUMERIC(10,6),                       -- Industry return 2 days ago
    avg_return_3d_lag   NUMERIC(10,6),                       -- Industry return 3 days ago
    consecutive_up_days   SMALLINT,                          -- Streak of consecutive up days (rally)
    consecutive_down_days SMALLINT,                          -- Streak of consecutive down days (drop)

    avg_pe              NUMERIC(12,4),                       -- cap-weighted avg P/E for the industry
    pct_above_sma_200   NUMERIC(10,4),                       -- % of constituents trading above 200-day SMA
    volatility_20d      NUMERIC(10,6),                       -- avg 20-day realized volatility across constituents
    sentiment_level     fin_markets.sentiment_level,         -- AI-driven aggregate sentiment for the industry

    UNIQUE (industry_stat_id),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);

CREATE INDEX IF NOT EXISTS idx_industry_stat_aggregs_created  ON fin_markets.industry_stat_aggregs (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_industry_stat_aggregs_stat_id  ON fin_markets.industry_stat_aggregs (industry_stat_id);


-- ============================================================
-- security_risks — per-security risk snapshot (market, credit, liquidity)
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.security_risks (
    security_id             BIGINT          NOT NULL REFERENCES fin_markets.securities (id),
    security_ext_id         BIGINT          REFERENCES fin_markets.security_exts (id),          -- fundamentals context: beta, debt_to_equity, net_margin via → security_ext_aggregs
    trade_stat_aggreg_id    BIGINT          REFERENCES fin_markets.security_trade_stat_aggregs (id),  -- technicals context: volatility_20d via → security_trade_stat_aggregs
    news_id                 BIGINT          REFERENCES fin_markets.news (id),       -- triggering news

    -- Market risk (own: derived fields not stored elsewhere)
    var_95                  NUMERIC(10,6),                  -- 1-day 95% Value at Risk (as fraction of price)
    max_drawdown            NUMERIC(10,6),                  -- max drawdown over trailing window

    -- Sentiment risk (news-driven)
    sentiment_level         fin_markets.sentiment_level,    -- AI-assessed risk sentiment from recent news

    -- Composite score
    risk_score              NUMERIC(5,2),                   -- composite risk score 0–100 (higher = riskier)

    UNIQUE (security_id, published_at),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);

CREATE INDEX IF NOT EXISTS idx_sec_risks_sec_date      ON fin_markets.security_risks (security_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_sec_risks_created       ON fin_markets.security_risks (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sec_risks_sec_ext       ON fin_markets.security_risks (security_ext_id);
CREATE INDEX IF NOT EXISTS idx_sec_risks_trade_stat    ON fin_markets.security_risks (trade_stat_aggreg_id);
-- Risk screening: "top N highest-risk securities as of today"
CREATE INDEX IF NOT EXISTS idx_sec_risks_score_date    ON fin_markets.security_risks (risk_score DESC, published_at DESC);


-- ============================================================
-- industry_risks — per-industry risk snapshot per region per date
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.industry_risks (
    industry                TEXT            NOT NULL CHECK (fin_markets.is_enum('industry', industry)),
    region                  TEXT            NOT NULL CHECK (fin_markets.is_enum('region', region)),
    industry_stat_id        BIGINT          REFERENCES fin_markets.industry_stats (id),         -- breadth/flow/volatility/sentiment context via → industry_stats & industry_stat_aggregs
    news_id     BIGINT          REFERENCES fin_markets.news (id),       -- triggering news

    -- Aggregate risk metrics (own: derived fields not stored elsewhere)
    var_95                  NUMERIC(10,6),                  -- industry-level 1-day 95% VaR
    pct_high_risk           NUMERIC(10,4),                  -- % of constituents with risk_score > 75
    concentration_risk      NUMERIC(10,4),                  -- HHI or top-5 weight (higher = more concentrated)
    max_drawdown            NUMERIC(10,6),                  -- worst constituent drawdown in the industry

    -- Composite score
    risk_score              NUMERIC(5,2),                   -- composite industry risk score 0–100

    UNIQUE (industry, region, published_at),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);

CREATE INDEX IF NOT EXISTS idx_ind_risks_ind_region_date ON fin_markets.industry_risks (industry, region, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_ind_risks_created         ON fin_markets.industry_risks (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ind_risks_stat_id         ON fin_markets.industry_risks (industry_stat_id);

-- ============================================================
-- macro_economics_stats — derived stats per macro release
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.macro_economics_stats (
    macro_economics_id  BIGINT  NOT NULL REFERENCES fin_markets.macro_economics (id) ON DELETE CASCADE,
    UNIQUE (macro_economics_id),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);

-- ============================================================
-- macro_dynamics — cross-asset market snapshot per date/region
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.macro_dynamics (
    region  TEXT  CHECK (region IS NULL OR fin_markets.is_enum('region', region)),
    UNIQUE (region, published_at),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);

CREATE INDEX IF NOT EXISTS idx_macro_dyn_date ON fin_markets.macro_dynamics (published_at DESC);

-- ============================================================
-- macro_dynamics_stats — breadth/performance stats per macro_dynamics snapshot
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.macro_dynamics_stats (
    macro_dynamics_id  BIGINT  NOT NULL REFERENCES fin_markets.macro_dynamics (id) ON DELETE CASCADE,
    UNIQUE (macro_dynamics_id),
    PRIMARY KEY (id)
) INHERITS (fin_markets.basics);
