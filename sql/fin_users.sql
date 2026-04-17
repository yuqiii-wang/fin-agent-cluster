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
