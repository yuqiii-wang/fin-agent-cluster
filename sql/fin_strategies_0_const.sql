CREATE SCHEMA IF NOT EXISTS fin_strategies;

-- ============================================================
-- sentiment_level — 7-point directional outlook scale
-- Used on judgement_history (per-horizon) and all sentiment cols.
-- ============================================================
DO $$ BEGIN
    CREATE TYPE fin_strategies.sentiment_level AS ENUM (
        'VERY_NEGATIVE',
        'NEGATIVE',
        'SLIGHTLY_NEGATIVE',
        'NEUTRAL',
        'SLIGHTLY_POSITIVE',
        'POSITIVE',
        'VERY_POSITIVE'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- confidence_level — agent conviction in its own judgement
-- Used on judgement_history.*_confidence columns.
-- ============================================================
DO $$ BEGIN
    CREATE TYPE fin_strategies.confidence_level AS ENUM (
        'VERY_LOW',
        'LOW',
        'MEDIUM',
        'HIGH',
        'VERY_HIGH'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ============================================================
-- enum_const — centralized controlled-vocabulary lookup
-- Covers all fin_strategies TEXT columns validated by CHECK constraints
-- or soft convention (not worth a native ENUM).
-- sentiment_level / confidence_level remain native PG ENUMs for
-- performance on heavily-queried columns.
--
-- Columns:
--   type        vocabulary name   (matches the conceptual "enum" name)
--   subtype     optional grouping (e.g. GICS tier, market region)
--   short_value canonical code    — used in table column values
--   long_value  human label       — NULL when short_value is self-explanatory
--   description additional notes
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.enum_const (
    id          SERIAL  PRIMARY KEY,
    type        TEXT    NOT NULL,
    subtype     TEXT,
    short_value TEXT    NOT NULL,
    long_value  TEXT,
    description TEXT,
    UNIQUE (type, short_value)
);

-- ============================================================
-- Seed data
-- ============================================================

-- ── term_structure ───────────────────────────────────────────
-- Used in: sec_futures.term_structure, sec_options.iv_term_structure
INSERT INTO fin_strategies.enum_const (type, short_value, long_value, description) VALUES
    ('term_structure', 'CONTANGO',      'Contango',      'Far contracts priced above near contracts; typical storage/carry cost'),
    ('term_structure', 'BACKWARDATION', 'Backwardation', 'Near contracts priced above far contracts; supply scarcity or convenience yield'),
    ('term_structure', 'FLAT',          'Flat',          'Negligible spread across the term structure curve')
ON CONFLICT (type, short_value) DO NOTHING;

-- ── macro_regime ─────────────────────────────────────────────
-- Used in: sec_macro.macro_regime
INSERT INTO fin_strategies.enum_const (type, short_value, long_value, description) VALUES
    ('macro_regime', 'RISK_ON',  'Risk-On',  'Investors seeking yield; equities & credit favoured over safe-havens'),
    ('macro_regime', 'RISK_OFF', 'Risk-Off', 'Flight to safety; bonds, USD, gold preferred; equities under pressure'),
    ('macro_regime', 'NEUTRAL',  'Neutral',  'No clear directional regime bias')
ON CONFLICT (type, short_value) DO NOTHING;

-- ── horizon ──────────────────────────────────────────────────
-- Used in: sentiment_scale_calibration.horizon
INSERT INTO fin_strategies.enum_const (type, short_value, long_value, description) VALUES
    ('horizon', '1d', '1 Day',     'Next trading day (~1 calendar day)'),
    ('horizon', '1w', '1 Week',    'One week (7 calendar days)'),
    ('horizon', '1m', '1 Month',   'One month (30 calendar days)'),
    ('horizon', '3m', '3 Months',  'One quarter / season (90 calendar days)'),
    ('horizon', '6m', '6 Months',  'Half year (180 calendar days)'),
    ('horizon', '1y', '1 Year',    'Full year (360 calendar days)')
ON CONFLICT (type, short_value) DO NOTHING;
