CREATE SCHEMA IF NOT EXISTS fin_markets;

-- Enable pgvector extension for vector similarity search on embeddings.
CREATE EXTENSION IF NOT EXISTS vector;

-- input_raw
CREATE TABLE IF NOT EXISTS fin_markets.input_raw (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT REFERENCES fin_agents.user_queries (thread_id) ON DELETE SET NULL,
    node_name TEXT NOT NULL DEFAULT 'unknown',
    symbol TEXT NOT NULL,          -- ticker symbol, e.g. 'AAPL'
    source TEXT NOT NULL,          -- provider/client name/url: 'yfinance', 'https://example.com/', etc.
    method TEXT,                   -- method/endpoint name: 'get_company_profile', etc.
    cache_key TEXT NOT NULL,       -- sha256(source + method + serialised input) for cache lookup
    cache_ttl_seconds INTEGER NOT NULL DEFAULT 14400, -- how long the cache is valid (e.g. 4 hours = 14400 seconds)
    input JSONB NOT NULL DEFAULT '{}',                         -- data params/payload for request; empty if data is directly injected into output
    output JSONB NOT NULL DEFAULT '{}',                        -- response/output from the API; data injection
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS fin_markets_input_raw_cache_key_idx
    ON fin_markets.input_raw (cache_key, created_at DESC);
CREATE INDEX IF NOT EXISTS fin_markets_input_raw_thread_id_idx
    ON fin_markets.input_raw (thread_id);
CREATE INDEX IF NOT EXISTS fin_markets_input_raw_source_method_idx
    ON fin_markets.input_raw (source, method);


-- quant_stats: unified market data for non-derivative instrument types — equity, crypto, commodity, precious_metal, index
-- one row per (instrument_type, symbol, source, granularity, bar_time)
-- instrument_type = 'equity'    → symbol is the ticker (e.g. 'AAPL'); full OHLCV + all technicals
-- instrument_type = 'crypto'    → symbol is the spot pair (e.g. 'BTC-USD'); full OHLCV + all technicals
-- instrument_type = 'commodity'       → symbol is the futures ticker (e.g. 'NG=F', 'CL=F'); full OHLCV + all technicals
-- instrument_type = 'precious_metal'  → symbol is the precious-metal futures ticker (e.g. 'GC=F', 'SI=F'); full OHLCV + all technicals
-- instrument_type = 'index'           → symbol is the index ticker (e.g. '^SPX', '000001.SS'); OHLCV + technicals
-- all OHLCV and indicator columns are nullable until enough history is available
-- derivative instruments (futures, options) are stored in quant_derivative_stats
CREATE TABLE IF NOT EXISTS fin_markets.quant_stats (
    id              BIGSERIAL PRIMARY KEY,
    symbol          TEXT          NOT NULL,                    -- equity/index: the ticker itself; futures/options: underlying ticker,
                                                               -- or index name 'S&P 500', 'Nikkei 225'
    instrument_type TEXT          NOT NULL DEFAULT 'equity'
                        REFERENCES fin_markets.instrument_types(code),
    currency_code    TEXT          NOT NULL REFERENCES fin_markets.currencies (code),                    -- ISO 4217 currency code, e.g. 'USD', 'JPY'
    -- Data source and time axis
    source          TEXT          NOT NULL,                    -- 'yfinance', 'alpha_vantage', 'akshare'
    granularity     TEXT          NOT NULL
                        CHECK (granularity IN ('5min','15min','30min','1h','2h','1day','1mo')),
    bar_time        TIMESTAMPTZ   NOT NULL,                    -- bar open time (UTC)
    -- OHLCV (nullable until enough history is available)
    open            NUMERIC(20,8),
    high            NUMERIC(20,8),
    low             NUMERIC(20,8),
    close           NUMERIC(20,8),
    volume          NUMERIC(30,8)  NOT NULL DEFAULT 0,
    trade_count     INTEGER,                                   -- individual trades in bar (equity intraday)
    -- Moving Averages
    sma_20          NUMERIC(20,8),                             -- simple MA 20-period
    sma_50          NUMERIC(20,8),                             -- simple MA 50-period
    sma_200         NUMERIC(20,8),                             -- simple MA 200-period
    ema_12          NUMERIC(20,8),                             -- exponential MA 12-period
    ema_26          NUMERIC(20,8),                             -- exponential MA 26-period
    -- MACD (12/26/9)
    macd_line       NUMERIC(20,8),                             -- ema_12 - ema_26
    macd_signal     NUMERIC(20,8),                             -- 9-period EMA of macd_line
    macd_hist       NUMERIC(20,8),                             -- macd_line - macd_signal
    -- Momentum
    rsi_14          NUMERIC(8,4),                              -- RSI 14-period (0-100)
    stoch_k         NUMERIC(8,4),                              -- Stochastic %K (0-100)
    stoch_d         NUMERIC(8,4),                              -- Stochastic %D: 3-period SMA of %K
    -- Volatility
    atr_14          NUMERIC(20,8),                             -- Average True Range 14-period
    bb_upper        NUMERIC(20,8),                             -- Bollinger Band upper  (20, 2-sigma)
    bb_middle       NUMERIC(20,8),                             -- Bollinger Band middle (20-period SMA)
    bb_lower        NUMERIC(20,8),                             -- Bollinger Band lower  (20, 2-sigma)
    -- Trend / Directional Movement (ADX family)
    adx_14          NUMERIC(8,4),                              -- Average Directional Index 14-period (0-100)
    plus_di_14      NUMERIC(8,4),                              -- Plus Directional Indicator (+DI)
    minus_di_14     NUMERIC(8,4),                              -- Minus Directional Indicator (-DI)
    aroon_up_14     NUMERIC(8,4),                              -- Aroon Up  14-period (0-100)
    aroon_down_14   NUMERIC(8,4),                              -- Aroon Down 14-period (0-100)
    sar             NUMERIC(20,8),                             -- Parabolic SAR (stop-and-reverse price)
    -- Momentum (additional)
    willr_14        NUMERIC(8,4),                              -- Williams %R 14-period (-100 to 0)
    cci_20          NUMERIC(10,4),                             -- Commodity Channel Index 20-period
    mfi_14          NUMERIC(8,4),                              -- Money Flow Index 14-period (0-100)
    roc_10          NUMERIC(10,4),                             -- Rate of Change 10-period (%)
    -- Volatility (additional)
    natr_14         NUMERIC(8,4),                              -- Normalized ATR 14-period (%)
    -- Volume / Price-Volume
    vwap            NUMERIC(20,8),                             -- Volume-Weighted Average Price
    obv             NUMERIC(30,8),                             -- On-Balance Volume (cumulative)
    ad              NUMERIC(30,8),                             -- Chaikin A/D Line (cumulative)
    index_code      TEXT          REFERENCES fin_markets.market_indexes(code),  -- primary index the stock belongs to (e.g. 'SP500', 'HANG_SENG')
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS quant_stats_uniq
    ON fin_markets.quant_stats (instrument_type, symbol, source, granularity, bar_time);

CREATE INDEX IF NOT EXISTS fin_markets_quant_stats_lookup_idx
    ON fin_markets.quant_stats (symbol, instrument_type, granularity, bar_time DESC);
CREATE INDEX IF NOT EXISTS fin_markets_quant_stats_bar_time_idx
    ON fin_markets.quant_stats (bar_time DESC);
CREATE INDEX IF NOT EXISTS fin_markets_quant_stats_index_code_idx
    ON fin_markets.quant_stats (index_code, instrument_type, granularity, bar_time DESC);


-- quant_options_stats: per-contract options-chain snapshot — one row per individual
-- call/put contract (strike).  Written by step 1 of calculate_option_stats from the
-- structured options json extracted from a Yahoo-Finance-style options chain page.
-- Each contract_name is a full OSI symbol from which symbol, expiry_date, options_type
-- and strike are parsed (parse_contract_name).  The unique key keeps one latest snapshot
-- row per (symbol, source, contract_name); re-ingesting the same contract updates it.
CREATE TABLE IF NOT EXISTS fin_markets.quant_options_stats (
    id                 BIGSERIAL PRIMARY KEY,
    symbol             TEXT          NOT NULL,                 -- underlying ticker, e.g. 'AAPL'
    source             TEXT          NOT NULL,                 -- 'web_content', 'yfinance', 'alpha_vantage'
    contract_name      TEXT          NOT NULL,                 -- full OSI contract name, e.g. 'AAPL260601P00250000'
    options_type       TEXT          NOT NULL
                            CHECK (options_type IN ('call', 'put')),
    expiry_date        TIMESTAMPTZ   NOT NULL,                 -- contract maturity (UTC), parsed from OSI contract_name
    strike             NUMERIC(20,8) NOT NULL,                 -- strike price
    last_trade_date    TIMESTAMPTZ,                            -- last trade timestamp (UTC)
    last_price         NUMERIC(20,8),                          -- last traded price
    bid                NUMERIC(20,8),                          -- bid price
    ask                NUMERIC(20,8),                          -- ask price
    mid_price          NUMERIC(20,8) GENERATED ALWAYS AS (
                            CASE WHEN bid IS NOT NULL AND ask IS NOT NULL AND (bid + ask) > 0
                                 THEN (bid + ask) / 2
                                 ELSE NULL END
                        ) STORED,                              -- bid/ask midpoint
    price_change       NUMERIC(20,8),                          -- absolute change on the session
    pct_change         NUMERIC(10,4),                          -- percent change on the session
    volume             NUMERIC(30,8),                          -- contracts traded in session
    open_interest      NUMERIC(30,8),                          -- per-contract open interest
    implied_volatility NUMERIC(10,4),                          -- implied volatility (percent, e.g. 107.81)
    created_at         TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS quant_options_stats_uniq
    ON fin_markets.quant_options_stats (symbol, source, contract_name);
CREATE INDEX IF NOT EXISTS fin_markets_quant_options_stats_lookup_idx
    ON fin_markets.quant_options_stats (symbol, expiry_date DESC, options_type, strike);
CREATE INDEX IF NOT EXISTS fin_markets_quant_options_stats_created_at_idx
    ON fin_markets.quant_options_stats (symbol, source, created_at DESC);


-- news_stats: one row per normalised news article with AI-generated enrichment fields
-- deduped by url (or cache_key when url is absent); upsert on (source, url_hash)
CREATE TABLE IF NOT EXISTS fin_markets.news_stats (
    id              BIGSERIAL PRIMARY KEY,
    -- provenance
    input_raw_id    BIGINT        REFERENCES fin_markets.input_raw (id) ON DELETE SET NULL,
    source          TEXT          NOT NULL,                     -- 'yfinance', 'alpha_vantage', 'web_search'
    -- article identity
    symbol          TEXT,                                       -- primary ticker; NULL for topic news
    url             TEXT,                                       -- original article URL (for display/linking)
    url_hash        TEXT          NOT NULL,                     -- sha256(url or title) for deduplication
    title           TEXT          NOT NULL,
    content         TEXT,                                       -- full article text (if available); otherwise a snippet or summary from the provider
    source_name     TEXT,                                       -- publisher / media outlet name
    published_at    TIMESTAMPTZ,                                -- when the article was published (UTC)
    -- AI-generated enrichment
    summary         TEXT,                                       -- 2-3 sentence AI summary
    summary_embedding vector(768),                              -- 768-dim pgvector embedding (text-embedding-004 / qwen3-0.6b-emb)
    sentiment_level TEXT          REFERENCES fin_markets.sentiment_levels(code),
    topic           TEXT          REFERENCES fin_markets.news_topics(code),
                                                                -- level3 event code, e.g. 'earnings_beat' → news_impact_categories.code
    tags            TEXT[]        NOT NULL DEFAULT '{}',        -- free-form tags for display and filtering, e.g. ['earnings', 'optimistic']
    -- timestamps
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    CONSTRAINT news_stats_uniq UNIQUE (source, url_hash)
);

CREATE INDEX IF NOT EXISTS fin_markets_news_stats_symbol_idx
    ON fin_markets.news_stats (symbol, published_at DESC);
CREATE INDEX IF NOT EXISTS fin_markets_news_stats_sentiment_idx
    ON fin_markets.news_stats (symbol, sentiment_level, published_at DESC);
CREATE INDEX IF NOT EXISTS fin_markets_news_stats_published_at_idx
    ON fin_markets.news_stats (published_at DESC);
CREATE INDEX IF NOT EXISTS fin_markets_news_stats_impact_idx
    ON fin_markets.news_stats (topic, published_at DESC);
-- HNSW index for fast approximate nearest-neighbour cosine similarity on embeddings.
CREATE INDEX IF NOT EXISTS fin_markets_news_stats_embedding_hnsw_idx
    ON fin_markets.news_stats USING hnsw (summary_embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE summary_embedding IS NOT NULL;

 
-- quant_static_stats: slow-changing fundamental and catalyst data per security
-- unique key spans both types via COALESCE expression index
CREATE TABLE IF NOT EXISTS fin_markets.quant_static_stats (
    id              BIGSERIAL PRIMARY KEY,
    symbol          TEXT          NOT NULL,
    fin_report_date    TIMESTAMPTZ NOT NULL,                                -- financial report date

    revenue         NUMERIC(20,2),
    revenue_yoy     NUMERIC(8,4),                              -- YoY growth (%) — sourced from provider
    gross_profit    NUMERIC(20,2),
    operating_income NUMERIC(20,2),
    net_income      NUMERIC(20,2),
    eps_diluted     NUMERIC(10,4),
    -- Derived margins (generated from source cols)
    gross_margin    NUMERIC GENERATED ALWAYS AS (
                        CASE WHEN revenue IS NOT NULL AND revenue != 0
                             THEN ROUND(CAST(gross_profit    / revenue * 100 AS NUMERIC), 4)
                             ELSE NULL END
                    ) STORED,                                  -- gross_profit / revenue (%)
    operating_margin NUMERIC GENERATED ALWAYS AS (
                        CASE WHEN revenue IS NOT NULL AND revenue != 0
                             THEN ROUND(CAST(operating_income / revenue * 100 AS NUMERIC), 4)
                             ELSE NULL END
                    ) STORED,                                  -- operating_income / revenue (%)
    net_margin      NUMERIC GENERATED ALWAYS AS (
                        CASE WHEN revenue IS NOT NULL AND revenue != 0
                             THEN ROUND(CAST(net_income       / revenue * 100 AS NUMERIC), 4)
                             ELSE NULL END
                    ) STORED,                                  -- net_income / revenue (%)
    -- Leverage & cash (source columns)
    total_debt      NUMERIC(20,2),                             -- total debt (short + long term)
    shareholders_equity NUMERIC(20,2),                        -- total shareholders' equity
    free_cash_flow  NUMERIC(20,2),
    -- Leverage ratio (derived from source cols; not stored separately — not volatile)
    debt_to_equity  NUMERIC GENERATED ALWAYS AS (
                        CASE WHEN shareholders_equity IS NOT NULL AND shareholders_equity != 0
                             THEN ROUND(CAST(total_debt / shareholders_equity AS NUMERIC), 4)
                             ELSE NULL END
                    ) STORED,                                  -- total_debt / shareholders_equity
    -- Valuation multiples (at period_end close)
    pe_ratio        NUMERIC(10,4),
    forward_pe      NUMERIC(10,4),
    ev_ebitda       NUMERIC(10,4),
    market_cap      NUMERIC(24,2),
    -- Dividend
    dividend_per_share   NUMERIC(10,4) NOT NULL,                        -- declared dividend amount per share
    dividend_stability NUMERIC(4,2),                           -- dividend stability (%)
    dividend_record_date TIMESTAMPTZ,                           -- date of the dividend record
    dividend_payment_date TIMESTAMPTZ,                           -- date of the dividend payment

    fin_report_news_stats_id   BIGINT        REFERENCES fin_markets.news_stats(id) ON DELETE SET NULL,
    -- Index memberships (flattened from exchange lookup; primary + up to 3 others)
    primary_index_name      TEXT,                              -- primary index code, e.g. 'SP500', 'NASDAQ_100'
    primary_index_weight    NUMERIC(8,4),                      -- stock weight (%) in primary index; NULL if unavailable
    other_opt1_index_name   TEXT,                              -- secondary index code (optional)
    other_opt1_index_weight NUMERIC(8,4),
    other_opt2_index_name   TEXT,
    other_opt2_index_weight NUMERIC(8,4),
    other_opt3_index_name   TEXT,
    other_opt3_index_weight NUMERIC(8,4),

    analysis_estimate_price NUMERIC(10,4),
    analysis_estimate_date  TIMESTAMPTZ,

    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS fin_markets_quant_static_stats_symbol_idx
    ON fin_markets.quant_static_stats (symbol, fin_report_date DESC NULLS LAST);
CREATE UNIQUE INDEX IF NOT EXISTS quant_static_stats_symbol_fin_report_date_uniq
    ON fin_markets.quant_static_stats (symbol, fin_report_date)
    WHERE fin_report_date IS NOT NULL;
CREATE INDEX IF NOT EXISTS fin_markets_quant_static_stats_fin_report_date_news_idx
    ON fin_markets.quant_static_stats (fin_report_news_stats_id)
    WHERE fin_report_news_stats_id IS NOT NULL;



