CREATE SCHEMA IF NOT EXISTS fin_users;

-- Users table — supports guest, password and future OAuth accounts.
-- Nullable columns allow progressive profile enrichment without migration.
CREATE TABLE IF NOT EXISTS fin_users.users (
    id               VARCHAR(36)   PRIMARY KEY,          -- UUID = bearer token (guests) or surrogate PK
    username         VARCHAR(100)  NOT NULL UNIQUE,       -- e.g. guest_482910 or chosen handle
    display_name     VARCHAR(200),                        -- human-readable full name
    email            VARCHAR(320)  UNIQUE,                -- RFC 5321 max length; NULL for pure guests
    email_verified   BOOLEAN       NOT NULL DEFAULT FALSE,
    password_hash    VARCHAR(256),                        -- bcrypt/argon2 hash; NULL until user sets password
    avatar_url       TEXT,                                -- profile picture URL (uploaded or OAuth-provided)
    -- OAuth fields (all nullable until the provider links the account)
    oauth_provider   VARCHAR(50),                         -- e.g. 'google', 'github', 'microsoft'
    oauth_subject    VARCHAR(256),                        -- provider's stable user ID ("sub" claim)
    oauth_access_token  TEXT,                             -- short-lived access token (encrypted at rest recommended)
    oauth_refresh_token TEXT,                             -- long-lived refresh token
    oauth_token_expires_at TIMESTAMP,                    -- UTC expiry of the access token
    -- Metadata
    auth_type        VARCHAR(20)   NOT NULL DEFAULT 'guest',  -- 'guest' | 'password' | 'oauth'
    is_active        BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMP     NOT NULL DEFAULT NOW(),
    last_seen_at     TIMESTAMP     NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS users_oauth_idx
    ON fin_users.users (oauth_provider, oauth_subject)
    WHERE oauth_provider IS NOT NULL AND oauth_subject IS NOT NULL;


-- User preferences — one row per (user, node_name) pair.
-- node_name can be a concrete graph node (e.g. "conclusion_node") or the
-- sentinel "__global__" for preferences that apply across all nodes.
--
-- config JSONB shape (keys are optional — absent means "use default"):
--   human_in_the_loop  BOOLEAN   pause execution after this node and wait for
--                                 the user to review/approve the output before
--                                 the graph continues.
--   depth              TEXT      research thoroughness: "shallow"|"normal"|"deep"
--                                 (meaningful for research_subgraph, stats_node,
--                                  news_node, analyze_stats_node, analyze_news_node)
--   max_iterations     INTEGER   max agent loop iterations for deep-agent nodes
--   temperature        NUMERIC   LLM sampling temperature 0.0–2.0
--                                 (meaningful for conclusion_node, regional nodes)
--   detail_level       TEXT      output verbosity: "brief"|"standard"|"detailed"
--                                 (meaningful for conclusion_node, merge_node)
CREATE TABLE IF NOT EXISTS fin_users.user_preferences (
    id          BIGSERIAL    PRIMARY KEY,
    user_id     VARCHAR(36)  NOT NULL REFERENCES fin_users.users (id) ON DELETE CASCADE,
    node_name   TEXT         NOT NULL,   -- graph node name or "__global__"
    config      JSONB        NOT NULL DEFAULT '{}',
    updated_at  TIMESTAMP    NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_preferences_user_node UNIQUE (user_id, node_name)
);

CREATE INDEX IF NOT EXISTS user_preferences_user_id_idx
    ON fin_users.user_preferences (user_id);
