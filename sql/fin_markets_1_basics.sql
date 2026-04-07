CREATE SCHEMA IF NOT EXISTS fin_markets;


-- ============================================================
-- 3. entities — institutional entities
-- Companies, funds, banks, regulators, exchanges, etc.
-- that are relevant to financial markets.
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.entities (
    id              BIGSERIAL       PRIMARY KEY,
    name            TEXT            NOT NULL,                 -- legal / display name
    short_name      TEXT,                                     -- abbreviated name
    entity_type     TEXT            NOT NULL CHECK (fin_markets.is_enum('entity_type', entity_type)),
    parent_id       BIGINT          REFERENCES fin_markets.entities (id),  -- parent entity (subsidiary → parent)
    region          TEXT            CHECK (region IS NULL OR fin_markets.is_enum('region', region)),                       -- geographic region
    industry        TEXT            CHECK (industry IS NULL OR fin_markets.is_enum('industry', industry)),                  -- GICS sector
    lei             TEXT,                                     -- Legal Entity Identifier (ISO 17442)
    website         TEXT,
    description     TEXT,
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    extra           JSONB           NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    established_at  DATE                                      -- When this institution was founded or established (if known)
);

CREATE INDEX IF NOT EXISTS idx_entities_name            ON fin_markets.entities (name);
CREATE UNIQUE INDEX IF NOT EXISTS idx_entities_name_type ON fin_markets.entities (name, entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_type            ON fin_markets.entities (entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_region         ON fin_markets.entities (region)       WHERE region IS NOT NULL;
-- Screener: "all banks in the US"
CREATE INDEX IF NOT EXISTS idx_entities_type_region     ON fin_markets.entities (entity_type, region) WHERE region IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_entities_parent          ON fin_markets.entities (parent_id)     WHERE parent_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_entities_lei             ON fin_markets.entities (lei)           WHERE lei IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_entities_active          ON fin_markets.entities (is_active)     WHERE is_active = TRUE;

-- ============================================================
-- 1. securities — master security reference
-- The canonical source of truth for every tradeable instrument.
-- All other tables FK back here via security_id.
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.securities (
    id              BIGSERIAL       PRIMARY KEY,
    ticker          TEXT            NOT NULL,                -- e.g. AAPL, 0700.HK, USD
    name            TEXT            NOT NULL,                -- short display name
    parent_security_id   BIGINT          REFERENCES fin_markets.securities (id),  -- higher level portfolio / index (e.g. SPX for AAPL)
    security_type   TEXT            NOT NULL CHECK (fin_markets.is_enum('security_type', security_type)),
    exchange        TEXT            CHECK (exchange IS NULL OR fin_markets.is_enum('major_institution', exchange)),  -- exchange name (validated against major_institution enum)
    region          TEXT            CHECK (region IS NULL OR fin_markets.is_enum('region', region)),                       -- geographic region
    industry        TEXT            CHECK (industry IS NULL OR fin_markets.is_enum('industry', industry)),                 -- GICS sector
    description     TEXT,                                    -- security description / summary
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    extra           JSONB           NOT NULL DEFAULT '{}',   -- overflow / vendor-specific fields
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, exchange)
);

-- Fast lookups by ticker, type, sector, region
CREATE INDEX IF NOT EXISTS idx_securities_ticker        ON fin_markets.securities (ticker);

CREATE INDEX IF NOT EXISTS idx_securities_type          ON fin_markets.securities (security_type);
CREATE INDEX IF NOT EXISTS idx_securities_industry   ON fin_markets.securities (industry)      WHERE industry IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_securities_region       ON fin_markets.securities (region)       WHERE region IS NOT NULL;
-- Screener: "all active equities in healthcare" / "all ETFs in the US"
CREATE INDEX IF NOT EXISTS idx_securities_type_region   ON fin_markets.securities (security_type, region)   WHERE region IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_securities_type_industry ON fin_markets.securities (security_type, industry) WHERE industry IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_securities_exchange      ON fin_markets.securities (exchange)      WHERE exchange IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_securities_active        ON fin_markets.securities (is_active)     WHERE is_active = TRUE;

-- ============================================================
-- indexes — market index definitions
-- E.g. S&P 500, Nasdaq 100, FTSE 100, custom sector baskets.
-- The index itself is also a row in securities (security_type='INDEX').
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.indexes (
    id              BIGSERIAL       PRIMARY KEY,
    security_id     BIGINT          NOT NULL REFERENCES fin_markets.securities (id),  -- the INDEX security
    name            TEXT            NOT NULL,                 -- display name, e.g. "S&P 500"
    short_name      TEXT,                                     -- abbreviated, e.g. "SPX"
    description     TEXT,
    region          TEXT            CHECK (region IS NULL OR fin_markets.is_enum('region', region)),                       -- geographic region
    is_active       BOOLEAN         NOT NULL DEFAULT TRUE,
    extra           JSONB           NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (security_id)
);

CREATE INDEX IF NOT EXISTS idx_indexes_security         ON fin_markets.indexes (security_id);
-- NOTE: weighting lives on index_exts, not indexes; no index needed here.
CREATE INDEX IF NOT EXISTS idx_indexes_region           ON fin_markets.indexes (region)           WHERE region IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_indexes_active           ON fin_markets.indexes (is_active)         WHERE is_active = TRUE;
-- NOTE: index_constituents table removed; constituent data lives in index_ext_mapping_securities.

-- ============================================================
-- 2. trades — OHLCV price bars (daily / intraday)
-- Partitioned-ready by trade_date for large-scale data.
-- Covers equities, ETFs, crypto, FX, commodities, futures.
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.security_trades (
    id              BIGSERIAL       PRIMARY KEY,
    security_id     BIGINT          NOT NULL REFERENCES fin_markets.securities (id),
    trade_date      DATE            NOT NULL,                -- bar date (for daily)
    start_time       TIMESTAMPTZ,                             -- intraday bar start (NULL for daily)
    end_time         TIMESTAMPTZ,                             -- intraday bar end   (NULL for daily)
    interval        TEXT            NOT NULL DEFAULT '15m' CHECK (fin_markets.is_enum('trade_interval', interval)),
    open            NUMERIC(20,6)   NOT NULL,
    high            NUMERIC(20,6)   NOT NULL,
    low             NUMERIC(20,6)   NOT NULL,
    close           NUMERIC(20,6)   NOT NULL,
    volume          BIGINT,                                  -- share / contract volume, -- positive = long, negative = short
    trade_count     INTEGER,                                 -- number of individual trades in bar
    currency        TEXT            NOT NULL DEFAULT 'USD' CHECK (fin_markets.is_enum('currency', currency)),
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    UNIQUE (security_id, trade_date, interval, start_time)
);

-- Primary query pattern: "give me AAPL daily bars from 2024-01 to 2024-06"
CREATE INDEX IF NOT EXISTS idx_trades_sec_date          ON fin_markets.security_trades (security_id, trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_trades_date              ON fin_markets.security_trades (trade_date DESC);
CREATE INDEX IF NOT EXISTS idx_trades_interval          ON fin_markets.security_trades (interval);
CREATE INDEX IF NOT EXISTS idx_trades_sec_interval_date ON fin_markets.security_trades (security_id, interval, trade_date DESC);
-- Covering index for OHLCV retrieval without heap access on common daily queries
CREATE INDEX IF NOT EXISTS idx_trades_sec_date_covering ON fin_markets.security_trades (security_id, trade_date DESC) INCLUDE (open, high, low, close, volume) WHERE interval = '1d';


CREATE TABLE IF NOT EXISTS fin_markets.news (
    id              BIGSERIAL       PRIMARY KEY,
    external_id     TEXT            UNIQUE,                   -- dedup key from source
    data_source     TEXT            CHECK (data_source IS NULL OR fin_markets.is_enum('data_source', data_source)),  -- Reuters, Bloomberg, CNBC, Xinhua
    source_url      TEXT,
    published_at    TIMESTAMPTZ     NOT NULL,
    title           TEXT            NOT NULL,
    subtitle        TEXT,
    body            TEXT,                                     -- full article text
    category        TEXT            CHECK (category IS NULL OR fin_markets.is_enum('news_category', category)),    

    -- Classification / tagging
    industry        TEXT            CHECK (industry IS NULL OR fin_markets.is_enum('industry', industry)),                  -- GICS sector
    region          TEXT            CHECK (region IS NULL OR fin_markets.is_enum('region', region)),                       -- geographic region
    tags            TEXT[],                                   -- free-form tags array
    extra           JSONB           NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_news_published           ON fin_markets.news (published_at DESC);
CREATE INDEX IF NOT EXISTS idx_news_data_source        ON fin_markets.news (data_source);
CREATE INDEX IF NOT EXISTS idx_news_industry        ON fin_markets.news (industry)        WHERE industry IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_news_region              ON fin_markets.news (region)          WHERE region IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_news_tags                ON fin_markets.news USING GIN (tags)  WHERE tags IS NOT NULL;
-- Full text search on title + body
CREATE INDEX IF NOT EXISTS idx_news_title_fts           ON fin_markets.news USING GIN (to_tsvector('english', title));
CREATE INDEX IF NOT EXISTS idx_news_body_fts            ON fin_markets.news USING GIN (to_tsvector('english', body));
-- Time + category: most common dashboard query ("recent earnings news")
CREATE INDEX IF NOT EXISTS idx_news_published_category  ON fin_markets.news (published_at DESC, category) WHERE category IS NOT NULL;
-- Time + region: geopolitical / macro feeds
CREATE INDEX IF NOT EXISTS idx_news_published_region    ON fin_markets.news (published_at DESC, region)   WHERE region IS NOT NULL;
-- Time + industry: sector-specific news stream
CREATE INDEX IF NOT EXISTS idx_news_published_industry  ON fin_markets.news (published_at DESC, industry) WHERE industry IS NOT NULL;
