CREATE SCHEMA IF NOT EXISTS fin_strategies;

-- ============================================================
-- sentiment_scale_calibration
-- Stores calibration metadata for the dynamic sentiment → numeric
-- return mapping for a given security and forward-looking horizon.
-- Populated (or refreshed) by fin_strategies.calibrate_sentiment_scale().
--
-- max_rise / max_drop  — historical extremes in the lookback window
-- mean_return / std_return — distribution stats for the same window
-- All return values are simple price-return decimals (0.05 = +5%).
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sentiment_scale_calibration (
    id              BIGSERIAL       PRIMARY KEY,
    security_id     BIGINT          NOT NULL
        REFERENCES fin_markets.securities (id) ON DELETE CASCADE,
    horizon         TEXT            NOT NULL
        CHECK (horizon IN ('1d', '1w', '1m', '3m', '6m', '1y')),
    lookback_days   INTEGER         NOT NULL DEFAULT 730,   -- calendar-day lookback (≈ 2 trading years)
    from_date       DATE            NOT NULL,               -- earliest trade_date in the sample
    to_date         DATE            NOT NULL,               -- latest  trade_date in the sample
    sample_count    INTEGER         NOT NULL,               -- number of forward-return observations
    max_rise        NUMERIC(12, 6)  NOT NULL,               -- highest observed forward return  (+0.15 = +15 %)
    max_drop        NUMERIC(12, 6)  NOT NULL,               -- lowest  observed forward return  (-0.20 = -20 %)
    mean_return     NUMERIC(12, 6)  NOT NULL,
    std_return      NUMERIC(12, 6)  NOT NULL,
    computed_at     TIMESTAMPTZ     NOT NULL DEFAULT NOW(),
    extra           JSONB           NOT NULL DEFAULT '{}',
    UNIQUE (security_id, horizon)
);

CREATE INDEX IF NOT EXISTS idx_ssc_security_horizon
    ON fin_strategies.sentiment_scale_calibration (security_id, horizon);
CREATE INDEX IF NOT EXISTS idx_ssc_computed_at
    ON fin_strategies.sentiment_scale_calibration (computed_at DESC);

-- ============================================================
-- sentiment_numeric_bands
-- Per-calibration return-band boundaries for each sentiment_level.
-- The 7 sentiment levels map to 7 equal-probability quantile bands
-- derived from the empirical forward-return distribution.
--
-- lower_bound  inclusive lower threshold of the band
-- upper_bound  exclusive upper threshold; NULL for VERY_POSITIVE (unbounded above)
-- midpoint     representative value for the band (average of band boundaries)
-- ============================================================
CREATE TABLE IF NOT EXISTS fin_strategies.sentiment_numeric_bands (
    id              BIGSERIAL       PRIMARY KEY,
    calibration_id  BIGINT          NOT NULL
        REFERENCES fin_strategies.sentiment_scale_calibration (id) ON DELETE CASCADE,
    sentiment_level fin_strategies.sentiment_level  NOT NULL,
    lower_bound     NUMERIC(12, 6)  NOT NULL,
    upper_bound     NUMERIC(12, 6),                         -- NULL = unbounded above (VERY_POSITIVE only)
    midpoint        NUMERIC(12, 6)  NOT NULL,               -- representative numeric return for this band
    UNIQUE (calibration_id, sentiment_level)
);

CREATE INDEX IF NOT EXISTS idx_snb_calibration
    ON fin_strategies.sentiment_numeric_bands (calibration_id);

-- ============================================================
-- calibrate_sentiment_scale
-- Derives the sentiment → numeric-return mapping for one security
-- and one forward horizon by:
--   1. Pulling daily closing prices from fin_markets.security_trades
--      over p_lookback_days calendar days.
--   2. Computing p_horizon_days-ahead simple forward returns.
--   3. Splitting the return distribution into 7 equal-probability
--      quantile bands (cut-points at 1/7 … 6/7) and aligning them
--      to the sentiment_level enum from VERY_NEGATIVE → VERY_POSITIVE.
--   4. Upserting sentiment_scale_calibration and replacing the
--      corresponding sentiment_numeric_bands rows.
--
-- Parameters:
--   p_security_id    BIGINT  — FK to fin_markets.securities
--   p_horizon_days   INTEGER — forward horizon in natural (calendar) days
--                              1 = next_day / '1d'
--                              7 = one_week / '1w'
--                             30 = one_month / '1m'
--                             90 = one_quarter / '3m'
--                            180 = half_year / '6m'
--                            360 = one_year  / '1y'
--   p_lookback_days  INTEGER — calendar-day look back window (default 730)
--
-- Returns the upserted calibration id.
-- ============================================================
CREATE OR REPLACE FUNCTION fin_strategies.calibrate_sentiment_scale(
    p_security_id   BIGINT,
    p_horizon_days  INTEGER,
    p_lookback_days INTEGER DEFAULT 730
) RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    v_horizon_label  TEXT;
    v_from_date      DATE;
    v_to_date        DATE;
    v_sample_count   INTEGER;
    v_max_rise       NUMERIC(12,6);
    v_max_drop       NUMERIC(12,6);
    v_mean_return    NUMERIC(12,6);
    v_std_return     NUMERIC(12,6);
    v_calibration_id BIGINT;
    v_cutpoints      DOUBLE PRECISION[];
    v_levels         fin_strategies.sentiment_level[] := ARRAY[
        'VERY_NEGATIVE'::fin_strategies.sentiment_level,
        'NEGATIVE'::fin_strategies.sentiment_level,
        'SLIGHTLY_NEGATIVE'::fin_strategies.sentiment_level,
        'NEUTRAL'::fin_strategies.sentiment_level,
        'SLIGHTLY_POSITIVE'::fin_strategies.sentiment_level,
        'POSITIVE'::fin_strategies.sentiment_level,
        'VERY_POSITIVE'::fin_strategies.sentiment_level
    ];
    v_lo             NUMERIC(12,6);
    v_hi             NUMERIC(12,6);
    i                INTEGER;
BEGIN
    -- Map trading-day count to canonical horizon label
    v_horizon_label := CASE p_horizon_days
        WHEN 1   THEN '1d'
        WHEN 7   THEN '1w'
        WHEN 30  THEN '1m'
        WHEN 90  THEN '3m'
        WHEN 180 THEN '6m'
        WHEN 360 THEN '1y'
        ELSE RAISE_EXCEPTION('Unsupported horizon_days: %. Use 1, 7, 30, 90, 180, or 360.', p_horizon_days)
    END;

    -- --------------------------------------------------------
    -- 1. Aggregate distribution stats from forward returns
    -- --------------------------------------------------------
    WITH daily_closes AS (
        -- Resolve future_close via calendar-day arithmetic:
        -- find the first available trading day >= trade_date + p_horizon_days calendar days.
        SELECT
            t.trade_date,
            t.close,
            (
                SELECT t2.close
                FROM fin_markets.security_trades t2
                WHERE t2.security_id = p_security_id
                  AND t2.interval    = '1d'
                  AND t2.trade_date  >= (t.trade_date + (p_horizon_days || ' days')::INTERVAL)::DATE
                ORDER BY t2.trade_date ASC
                LIMIT 1
            ) AS future_close
        FROM fin_markets.security_trades t
        WHERE t.security_id = p_security_id
          AND t.interval    = '1d'
          AND t.trade_date  >= (CURRENT_DATE - (p_lookback_days || ' days')::INTERVAL)::DATE
          AND t.trade_date  <   CURRENT_DATE
    ),
    returns AS (
        SELECT
            trade_date,
            (future_close - close) / NULLIF(close, 0) AS fwd_return
        FROM daily_closes
        WHERE future_close IS NOT NULL
          AND close        IS NOT NULL
    )
    SELECT
        COUNT(*)::INTEGER,
        MAX(fwd_return),
        MIN(fwd_return),
        AVG(fwd_return),
        STDDEV(fwd_return),
        MIN(trade_date),
        MAX(trade_date)
    INTO
        v_sample_count,
        v_max_rise,
        v_max_drop,
        v_mean_return,
        v_std_return,
        v_from_date,
        v_to_date
    FROM returns;

    IF v_sample_count IS NULL OR v_sample_count < 14 THEN
        RAISE EXCEPTION
            'Insufficient data: % observations for security_id=%, horizon=%d days. Need ≥ 14.',
            COALESCE(v_sample_count, 0), p_security_id, p_horizon_days;
    END IF;

    -- --------------------------------------------------------
    -- 2. Upsert calibration metadata row
    -- --------------------------------------------------------
    INSERT INTO fin_strategies.sentiment_scale_calibration
        (security_id, horizon, lookback_days, from_date, to_date, sample_count,
         max_rise, max_drop, mean_return, std_return, computed_at)
    VALUES
        (p_security_id, v_horizon_label, p_lookback_days,
         v_from_date, v_to_date, v_sample_count,
         v_max_rise, v_max_drop, v_mean_return, v_std_return, NOW())
    ON CONFLICT (security_id, horizon) DO UPDATE SET
        lookback_days = EXCLUDED.lookback_days,
        from_date     = EXCLUDED.from_date,
        to_date       = EXCLUDED.to_date,
        sample_count  = EXCLUDED.sample_count,
        max_rise      = EXCLUDED.max_rise,
        max_drop      = EXCLUDED.max_drop,
        mean_return   = EXCLUDED.mean_return,
        std_return    = EXCLUDED.std_return,
        computed_at   = EXCLUDED.computed_at
    RETURNING id INTO v_calibration_id;

    -- --------------------------------------------------------
    -- 3. Compute 6 quantile cut-points (1/7 … 6/7)
    -- --------------------------------------------------------
    WITH daily_closes AS (
        SELECT
            t.close,
            (
                SELECT t2.close
                FROM fin_markets.security_trades t2
                WHERE t2.security_id = p_security_id
                  AND t2.interval    = '1d'
                  AND t2.trade_date  >= (t.trade_date + (p_horizon_days || ' days')::INTERVAL)::DATE
                ORDER BY t2.trade_date ASC
                LIMIT 1
            ) AS future_close
        FROM fin_markets.security_trades t
        WHERE t.security_id = p_security_id
          AND t.interval    = '1d'
          AND t.trade_date  >= (CURRENT_DATE - (p_lookback_days || ' days')::INTERVAL)::DATE
          AND t.trade_date  <   CURRENT_DATE
    ),
    returns AS (
        SELECT (future_close - close) / NULLIF(close, 0) AS fwd_return
        FROM daily_closes
        WHERE future_close IS NOT NULL AND close IS NOT NULL
    )
    SELECT
        percentile_cont(ARRAY[1.0/7, 2.0/7, 3.0/7, 4.0/7, 5.0/7, 6.0/7])
            WITHIN GROUP (ORDER BY fwd_return)
    INTO v_cutpoints
    FROM returns;

    -- --------------------------------------------------------
    -- 4. Replace sentiment_numeric_bands for this calibration
    -- --------------------------------------------------------
    DELETE FROM fin_strategies.sentiment_numeric_bands
    WHERE calibration_id = v_calibration_id;

    FOR i IN 1..7 LOOP
        -- lower bound: max_drop for first band, else previous cut-point
        v_lo := CASE WHEN i = 1 THEN v_max_drop
                     ELSE v_cutpoints[i - 1]::NUMERIC(12,6)
                END;
        -- upper bound: next cut-point, or NULL (unbounded) for VERY_POSITIVE
        v_hi := CASE WHEN i = 7 THEN NULL
                     ELSE v_cutpoints[i]::NUMERIC(12,6)
                END;

        INSERT INTO fin_strategies.sentiment_numeric_bands
            (calibration_id, sentiment_level, lower_bound, upper_bound, midpoint)
        VALUES (
            v_calibration_id,
            v_levels[i],
            v_lo,
            v_hi,
            -- midpoint: average of band edges; use max_rise as ceiling for top band
            CASE
                WHEN i = 7 THEN (v_cutpoints[6]::NUMERIC(12,6) + v_max_rise) / 2
                ELSE (v_lo + v_hi) / 2
            END
        );
    END LOOP;

    RETURN v_calibration_id;
END;
$$;

-- ============================================================
-- map_return_to_sentiment
-- Lookup utility: given a security, horizon label, and an
-- observed (or projected) price return, returns the matching
-- sentiment_level from the latest calibration.
-- Returns NULL when no calibration exists for the pair.
--
-- Example:
--   SELECT fin_strategies.map_return_to_sentiment(42, '1w', 0.031);
--   → 'SLIGHTLY_POSITIVE'
-- ============================================================
CREATE OR REPLACE FUNCTION fin_strategies.map_return_to_sentiment(
    p_security_id   BIGINT,
    p_horizon       TEXT,
    p_return        NUMERIC
) RETURNS fin_strategies.sentiment_level
LANGUAGE sql
STABLE
AS $$
    SELECT b.sentiment_level
    FROM fin_strategies.sentiment_scale_calibration c
    JOIN fin_strategies.sentiment_numeric_bands     b ON b.calibration_id = c.id
    WHERE c.security_id = p_security_id
      AND c.horizon     = p_horizon
      AND p_return >= b.lower_bound
      AND (b.upper_bound IS NULL OR p_return < b.upper_bound)
    ORDER BY c.computed_at DESC
    LIMIT 1;
$$;
