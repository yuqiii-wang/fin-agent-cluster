CREATE SCHEMA IF NOT EXISTS fin_strategies;

-- ============================================================
-- analysis_snapshots — cached LLM analysis outputs per security per day
--
-- Each graph node that produces a textual LLM analysis (market_data,
-- fundamental, technical, news, risk) writes its output here.
-- Subsequent requests for the same (security_id, node_name) within
-- the staleness window are served from this table, skipping LLM calls.
--
-- node_name   — matches the LangGraph node identifier string
-- stale_after — timestamp after which the snapshot should be re-generated
-- content     — the full LLM output text
-- token_count — optional prompt+completion token count for cost tracking
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.analysis_snapshots (
    id              BIGSERIAL       PRIMARY KEY,
    security_id     BIGINT          NOT NULL
        REFERENCES fin_markets.securities (id) ON DELETE CASCADE,
    node_name       TEXT            NOT NULL,               -- 'market_data_collector', 'fundamental_analyzer', etc.
    published_at    TIMESTAMPTZ     NOT NULL DEFAULT NOW(), -- when the snapshot was created
    stale_after     TIMESTAMPTZ     NOT NULL,               -- after this timestamp, re-run the LLM
    content         TEXT            NOT NULL,               -- full LLM output text
    token_count     INTEGER,                                -- optional: total tokens used
    extra           JSONB           NOT NULL DEFAULT '{}',  -- prompt params, model version, etc.
    UNIQUE (security_id, node_name, published_at)
);

CREATE INDEX IF NOT EXISTS idx_analysis_snap_sec_node_pub
    ON fin_strategies.analysis_snapshots (security_id, node_name, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_analysis_snap_stale
    ON fin_strategies.analysis_snapshots (security_id, node_name, stale_after DESC);
