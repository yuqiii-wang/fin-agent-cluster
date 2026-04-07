CREATE SCHEMA IF NOT EXISTS fin_markets;

CREATE TABLE IF NOT EXISTS fin_markets.relationship_basics (
    id              BIGSERIAL       PRIMARY KEY,
    relationship_type   TEXT            NOT NULL CHECK (fin_markets.is_enum('relationship_type', relationship_type)),  -- e.g. 'index_constituent', 'peer', 'supplier', 'customer', etc.
    published_at    TIMESTAMPTZ     NOT NULL,             -- The timestamp when the data is effective (e.g. trade_date for OHLCV, report_date for fundamentals)
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT NOW()
);

-- ============================================================
-- security_2_security — normalized 2: security → security by relationships
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.security_2_security (
    primary_id                         BIGINT      NOT NULL REFERENCES fin_markets.securities (id),
    related_id                         BIGINT      NOT NULL REFERENCES fin_markets.securities (id),
    relationship_correlation           NUMERIC(5,4),                                                   -- optional correlation coefficient (e.g. price correlation, supply chain correlation, etc.) to quantify relationship strength
    relationship_estimate_since        TIMESTAMPTZ                                                  -- optional timestamp indicating since when the relationship is estimated to hold (e.g. based on first observed co-movement, supply chain data, etc.)
) INHERITS (fin_markets.relationship_basics);
CREATE INDEX IF NOT EXISTS idx_security_2_security_primary_id_2_related_id ON fin_markets.security_2_security (primary_id, related_id);
CREATE INDEX IF NOT EXISTS idx_security_2_security_related_id               ON fin_markets.security_2_security (related_id);

-- ============================================================
-- index_2_security — normalized 2: snapshot → security + weight
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.index_2_security (
    primary_id      BIGINT      NOT NULL REFERENCES fin_markets.index_stats (id) ON DELETE CASCADE,
    related_id      BIGINT      NOT NULL REFERENCES fin_markets.securities (id),
    weight_pct      NUMERIC(10,6)   NOT NULL                 -- constituent weight within the index (0–1)
) INHERITS (fin_markets.relationship_basics);

-- Constituent lookup: "get all securities for index snapshot X" (primary access pattern)
CREATE INDEX IF NOT EXISTS idx_index_2_security_primary_id_2_related_id ON fin_markets.index_2_security (primary_id, related_id);
-- Reverse lookup: "which index snapshots contain security Y?"
CREATE INDEX IF NOT EXISTS idx_index_2_security_related_id               ON fin_markets.index_2_security (related_id);

CREATE TABLE IF NOT EXISTS fin_markets.index_2_industry (
    primary_id       BIGINT                      NOT NULL REFERENCES fin_markets.index_stat_aggregs (id) ON DELETE CASCADE,
    related_id       TEXT                        NOT NULL CHECK (fin_markets.is_enum('industry', related_id))
) INHERITS (fin_markets.relationship_basics);
CREATE INDEX IF NOT EXISTS idx_index_2_industry_primary_id_2_related_id ON fin_markets.index_2_industry (primary_id, related_id);
CREATE INDEX IF NOT EXISTS idx_index_2_industry_related_id               ON fin_markets.index_2_industry (related_id);


-- ============================================================
-- news_ext_2_news_ext — impacted news articles per news article
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.news_ext_2_news_ext (
    primary_id                          BIGINT      NOT NULL REFERENCES fin_markets.news_exts (id) ON DELETE CASCADE,
    related_id                          BIGINT      NOT NULL REFERENCES fin_markets.news_exts (id) ON DELETE CASCADE,
    relationship_confidence            fin_markets.sentiment_level               NOT NULL              -- e.g. 'positive', 'negative', 'neutral' to indicate relationship sentiment/impact direction
) INHERITS (fin_markets.relationship_basics);
CREATE INDEX IF NOT EXISTS idx_news_ext_2_news_ext_primary_id_2_related_id ON fin_markets.news_ext_2_news_ext (primary_id, related_id);
CREATE INDEX IF NOT EXISTS idx_news_ext_2_news_ext_related_id               ON fin_markets.news_ext_2_news_ext (related_id);

CREATE TABLE IF NOT EXISTS fin_markets.news_ext_2_security (
    primary_id      BIGINT      NOT NULL REFERENCES fin_markets.news_exts (id) ON DELETE CASCADE,
    related_id      BIGINT      NOT NULL REFERENCES fin_markets.securities (id),
    relationship_confidence            fin_markets.sentiment_level               NOT NULL              -- e.g. 'positive', 'negative', 'neutral' to indicate relationship sentiment/impact direction
) INHERITS (fin_markets.relationship_basics);
CREATE INDEX IF NOT EXISTS idx_news_ext_2_security_primary_id_2_related_id ON fin_markets.news_ext_2_security (primary_id, related_id);
CREATE INDEX IF NOT EXISTS idx_news_ext_2_security_related_id               ON fin_markets.news_ext_2_security (related_id);

CREATE TABLE IF NOT EXISTS fin_markets.news_ext_2_entity (
    primary_id      BIGINT      NOT NULL REFERENCES fin_markets.news_exts (id) ON DELETE CASCADE,
    related_id      BIGINT      NOT NULL REFERENCES fin_markets.entities (id),
    relationship_confidence            fin_markets.sentiment_level               NOT NULL              -- e.g. 'positive', 'negative', 'neutral' to indicate relationship sentiment/impact direction
) INHERITS (fin_markets.relationship_basics);
CREATE INDEX IF NOT EXISTS idx_news_ext_2_entity_primary_id_2_related_id ON fin_markets.news_ext_2_entity (primary_id, related_id);
CREATE INDEX IF NOT EXISTS idx_news_ext_2_entity_related_id               ON fin_markets.news_ext_2_entity (related_id);

-- news_ext_2_industry — impacted industries per news article
CREATE TABLE IF NOT EXISTS fin_markets.news_ext_2_industry (
    primary_id      BIGINT                      NOT NULL REFERENCES fin_markets.news_exts (id) ON DELETE CASCADE,
    related_id      TEXT                        NOT NULL CHECK (fin_markets.is_enum('industry', related_id)),
    relationship_confidence            fin_markets.sentiment_level               NOT NULL              -- e.g. 'positive', 'negative', 'neutral' to indicate relationship sentiment/impact direction
) INHERITS (fin_markets.relationship_basics);
CREATE INDEX IF NOT EXISTS idx_news_ext_2_industry_primary_id_2_related_id ON fin_markets.news_ext_2_industry (primary_id, related_id);
CREATE INDEX IF NOT EXISTS idx_news_ext_2_industry_related_id               ON fin_markets.news_ext_2_industry (related_id);

-- news_ext_2_region — impacted regions per news article
CREATE TABLE IF NOT EXISTS fin_markets.news_ext_2_region (
    primary_id      BIGINT                      NOT NULL REFERENCES fin_markets.news_exts (id) ON DELETE CASCADE,
    related_id      TEXT                        NOT NULL CHECK (fin_markets.is_enum('region', related_id)),
    relationship_confidence            fin_markets.sentiment_level               NOT NULL              -- e.g. 'positive', 'negative', 'neutral' to indicate relationship sentiment/impact direction
) INHERITS (fin_markets.relationship_basics);
CREATE INDEX IF NOT EXISTS idx_news_ext_2_region_primary_id_2_related_id ON fin_markets.news_ext_2_region (primary_id, related_id);
CREATE INDEX IF NOT EXISTS idx_news_ext_2_region_related_id               ON fin_markets.news_ext_2_region (related_id);


-- ============================================================
-- news_ext_2_news_topic — M:N bridge: article ↔ topic node
-- This table is the "node" in the (time × topic) grid:
--   X-axis  →  news.published_at  (when)
--   Y-axis  →  news_topics.path                (what topic, in the tree)
--   Node    →  one row here per (article, topic) pair
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_markets.news_ext_2_news_topic (
    primary_id             BIGINT          NOT NULL REFERENCES fin_markets.news_exts (id) ON DELETE CASCADE,
    related_id                BIGINT          NOT NULL REFERENCES fin_markets.news_topics (id),
    relationship_confidence            fin_markets.sentiment_level               NOT NULL,             -- e.g. 'positive', 'negative', 'neutral' to indicate relationship sentiment/impact direction
    PRIMARY KEY (primary_id, related_id)
) INHERITS (fin_markets.basics);
CREATE INDEX IF NOT EXISTS idx_news_ext_2_news_topic_primary_id_2_related_id ON fin_markets.news_ext_2_news_topic (primary_id, related_id);
CREATE INDEX IF NOT EXISTS idx_news_ext_2_news_topic_related_id               ON fin_markets.news_ext_2_news_topic (related_id);