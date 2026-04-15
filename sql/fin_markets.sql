CREATE SCHEMA IF NOT EXISTS fin_markets;

-- news_raw: logs every call to a news/search API (yfinance news, alpha vantage news & sentiment, web search)
-- 4-hour cache — same cache_key within the TTL returns the stored output
-- thread_id is nullable so the same cached record can be reused across different threads
CREATE TABLE IF NOT EXISTS fin_markets.news_raw (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT REFERENCES fin_agents.user_queries (thread_id) ON DELETE SET NULL,
    node_name TEXT NOT NULL DEFAULT 'unknown',
    source TEXT NOT NULL,          -- provider/client name: 'fmp', 'yfinance', 'web_search', etc.
    method TEXT NOT NULL,          -- method/endpoint name: 'get_company_profile', etc.
    cache_key TEXT NOT NULL,       -- sha256(source + method + serialised input) for cache lookup
    input JSONB NOT NULL DEFAULT '{}',
    output JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS fin_markets_news_raw_cache_key_idx
    ON fin_markets.news_raw (cache_key, created_at DESC);
CREATE INDEX IF NOT EXISTS fin_markets_news_raw_thread_id_idx
    ON fin_markets.news_raw (thread_id);
CREATE INDEX IF NOT EXISTS fin_markets_news_raw_source_method_idx
    ON fin_markets.news_raw (source, method);

-- quant_raw: logs every call to a market-data API (yfinance, alpha_vantage)
-- 4-hour cache — same cache_key within the TTL returns the stored output
-- thread_id is nullable so the same cached record can be reused across different threads
CREATE TABLE IF NOT EXISTS fin_markets.quant_raw (
    id BIGSERIAL PRIMARY KEY,
    thread_id TEXT REFERENCES fin_agents.user_queries (thread_id) ON DELETE SET NULL,
    node_name TEXT NOT NULL DEFAULT 'unknown',
    source TEXT NOT NULL,          -- provider: 'yfinance', 'alpha_vantage'
    method TEXT NOT NULL,          -- 'daily_ohlcv', 'intraday_ohlcv', 'quote', 'overview'
    symbol TEXT NOT NULL,          -- ticker symbol, e.g. 'AAPL'
    cache_key TEXT NOT NULL,       -- sha256(source + method + symbol + serialised params)
    input JSONB NOT NULL DEFAULT '{}',
    output JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS fin_markets_quant_raw_cache_key_idx
    ON fin_markets.quant_raw (cache_key, created_at DESC);
CREATE INDEX IF NOT EXISTS fin_markets_quant_raw_thread_id_idx
    ON fin_markets.quant_raw (thread_id);
CREATE INDEX IF NOT EXISTS fin_markets_quant_raw_symbol_method_idx
    ON fin_markets.quant_raw (symbol, method, created_at DESC);

-- quant_stats: unified market data for all instrument types — equity, index, futures, and options
-- one row per (instrument_type, symbol, source, granularity, bar_time, contract_ticker, expiry, option_type)
-- instrument_type = 'equity'  → symbol is the ticker (e.g. 'AAPL'); full OHLCV + all technicals
-- instrument_type = 'index'   → symbol is the index ticker (e.g. '^SPX', '000001.SS'); OHLCV + technicals
-- instrument_type = 'futures' → symbol is the underlying ticker; contract_ticker is the dated contract; daily OHLCV
-- instrument_type = 'options' → symbol is the underlying ticker; options flow columns populated; daily snapshot
-- all OHLCV and indicator columns are nullable: absent for options flow rows and until enough history is available
-- granularity for futures / options is typically '1day'
CREATE TABLE IF NOT EXISTS fin_markets.quant_stats (
    id              BIGSERIAL PRIMARY KEY,
    symbol          TEXT          NOT NULL,                    -- equity/index: the ticker itself; futures/options: underlying ticker,
                                                               -- or index name 'S&P 500', 'Nikkei 225'
    instrument_type TEXT          NOT NULL DEFAULT 'equity'
                        CHECK (instrument_type IN ('equity', 'index', 'futures', 'options')),
    currency_code    TEXT          NOT NULL REFERENCES fin_markets.currencies (code),                    -- ISO 4217 currency code, e.g. 'USD', 'JPY'
    -- Derivative metadata (instrument_type = 'futures' or 'options')
    contract_ticker TEXT,                                      -- futures: dated contract ticker, e.g. 'ESM25', 'CLK25'
    expiry          TEXT          CHECK (expiry IS NULL OR expiry IN ('1mo', '6mo')),
    -- Options metadata (instrument_type = 'options')
    option_type     TEXT          CHECK (option_type IS NULL OR option_type IN ('call', 'put', 'aggregate')),
    -- Data source and time axis
    source          TEXT          NOT NULL,                    -- 'yfinance', 'alpha_vantage', 'akshare'
    granularity     TEXT          NOT NULL
                        CHECK (granularity IN ('1min','5min','15min','30min','1h','2h','1day','1mo')),
    bar_time        TIMESTAMPTZ   NOT NULL,                    -- bar open time (UTC); snapshot time for options
    -- OHLCV (NULL for options-flow rows which carry no price bars)
    open            NUMERIC(20,8),
    high            NUMERIC(20,8),
    low             NUMERIC(20,8),
    close           NUMERIC(20,8),
    volume          NUMERIC(30,8)  NOT NULL DEFAULT 0,
    trade_count     INTEGER,                                   -- individual trades in bar (equity intraday)
    open_interest   NUMERIC(30,8),                             -- futures: contracts outstanding; options: total OI
    -- Options flow (instrument_type = 'options')
    calls_oi        BIGINT,                                    -- calls open interest
    puts_oi         BIGINT,                                    -- puts open interest
    calls_puts_ratio NUMERIC(10,4),                            -- calls / puts OI ratio
    net_flow        TEXT          CHECK (net_flow IS NULL OR net_flow IN ('calls_dominant', 'puts_dominant', 'neutral')),
    query_used      TEXT,                                      -- search query used to fetch options data
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
    region          TEXT          REFERENCES fin_markets.regions(code), -- market region, e.g. 'us', 'jp', 'cn'
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- Expression-based unique index handles nullable discriminator columns across all instrument types
CREATE UNIQUE INDEX IF NOT EXISTS quant_stats_uniq
    ON fin_markets.quant_stats (
        instrument_type, symbol, source, granularity, bar_time,
        COALESCE(contract_ticker, ''),
        COALESCE(expiry, ''),
        COALESCE(option_type, '')
    );

CREATE INDEX IF NOT EXISTS fin_markets_quant_stats_lookup_idx
    ON fin_markets.quant_stats (symbol, instrument_type, granularity, bar_time DESC);
CREATE INDEX IF NOT EXISTS fin_markets_quant_stats_bar_time_idx
    ON fin_markets.quant_stats (bar_time DESC);
CREATE INDEX IF NOT EXISTS fin_markets_quant_stats_region_idx
    ON fin_markets.quant_stats (region, instrument_type, granularity, bar_time DESC);


-- news_stats: one row per normalised news article with AI-generated enrichment fields
-- deduped by url (or cache_key when url is absent); upsert on (source, url_hash)
CREATE TABLE IF NOT EXISTS fin_markets.news_stats (
    id              BIGSERIAL PRIMARY KEY,
    -- provenance
    news_raw_id     BIGINT        REFERENCES fin_markets.news_raw (id) ON DELETE SET NULL,
    source          TEXT          NOT NULL,                     -- 'yfinance', 'alpha_vantage', 'web_search'
    -- article identity
    symbol          TEXT,                                       -- primary ticker; NULL for topic news
    url_hash        TEXT          NOT NULL,                     -- sha256(url) for dedup index
    title           TEXT          NOT NULL,
    source_name     TEXT,                                       -- publisher / media outlet name
    published_at    TIMESTAMPTZ,                                -- when the article was published (UTC)
    -- AI-generated enrichment
    ai_summary      TEXT,                                       -- 2-3 sentence AI summary
    summary_embedding FLOAT[],                                 -- embedding of ai_summary via Google text-embedding-004 (768 dims); stored as float array, no pgvector required
    sentiment_level TEXT          REFERENCES fin_markets.sentiment_levels(code),
    sector          TEXT          REFERENCES fin_markets.news_sectors(code),
    topic_level1    TEXT          REFERENCES fin_markets.news_topic_level1(code),
    topic_level2    TEXT          REFERENCES fin_markets.news_topic_level2(code),
    impact_category TEXT          REFERENCES fin_markets.news_impact_categories (code),
                                                                -- level3 event code, e.g. 'earnings_beat' → news_impact_categories.code
    topics          TEXT[]        NOT NULL DEFAULT '{}',        -- free-form tags beyond the structured classification
    region          TEXT REFERENCES fin_markets.regions(code), -- geographic region of the news: 'us', 'cn', 'gb', etc.
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
    ON fin_markets.news_stats (topic_level1, topic_level2, published_at DESC);
CREATE INDEX IF NOT EXISTS fin_markets_news_stats_impact_category_idx
    ON fin_markets.news_stats (impact_category, published_at DESC);


-- sec_profiles: one row per security — slow-changing identity and profile data
-- symbol is the primary ticker; symbols[] holds all cross-listing tickers for the same company
-- (e.g. Alibaba: symbol='BABA', symbols=['BABA', '9988.HK'])
-- biz_regions is a free-form list of fin_markets.regions codes where the company operates
CREATE TABLE IF NOT EXISTS fin_markets.sec_profiles (
    id              BIGSERIAL PRIMARY KEY,
    symbol          TEXT          NOT NULL UNIQUE,             -- primary ticker, e.g. 'AAPL', 'BABA'
    symbols         TEXT[]        NOT NULL DEFAULT '{}',       -- all known tickers across exchanges, e.g. ['BABA', '9988.HK']
    region          TEXT          REFERENCES fin_markets.regions(code),
    currency_code   TEXT          REFERENCES fin_markets.currencies(code),
    name            TEXT,                                      -- company/security name for display
    biz_regions     TEXT[]        NOT NULL DEFAULT '{}',       -- fin_markets.regions codes where company operates
    intro           TEXT,                                      -- short plain-language description of the company/security
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS fin_markets_sec_profiles_symbol_idx
    ON fin_markets.sec_profiles (symbol);
CREATE INDEX IF NOT EXISTS fin_markets_sec_profiles_region_idx
    ON fin_markets.sec_profiles (region);


-- quant_static_stats: slow-changing fundamental and catalyst data per security
-- unique key spans both types via COALESCE expression index
CREATE TABLE IF NOT EXISTS fin_markets.quant_static_stats (
    id              BIGSERIAL PRIMARY KEY,
    symbol          TEXT          NOT NULL
                        REFERENCES fin_markets.sec_profiles(symbol) ON DELETE CASCADE,

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
    dividend_per_share   NUMERIC(10,4),                        -- declared dividend amount per share

    published_at    TIMESTAMPTZ,                               -- when the news was published (UTC)
    news_stats_id   BIGINT        REFERENCES fin_markets.news_stats(id) ON DELETE SET NULL,

    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS fin_markets_quant_static_stats_symbol_idx
    ON fin_markets.quant_static_stats (symbol, published_at DESC);
CREATE INDEX IF NOT EXISTS fin_markets_quant_static_stats_news_idx
    ON fin_markets.quant_static_stats (news_stats_id)
    WHERE news_stats_id IS NOT NULL;



