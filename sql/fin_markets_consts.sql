CREATE SCHEMA IF NOT EXISTS fin_markets;

-- fin_markets_consts.sql
-- Static reference data for the fin_markets schema.
-- Must be applied BEFORE fin_markets.sql.

-- ---------------------------------------------------------------------------
-- sentiment_levels: 9-point directional sentiment scale
--   code       → snake_case key referenced as FK by other tables
--   score_min/max → normalised score range [-1, 1] for each bucket
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_markets.sentiment_levels (
    code        TEXT          PRIMARY KEY,
    label       TEXT          NOT NULL,
    description TEXT,
    sort_order  INTEGER       NOT NULL DEFAULT 0,
    score_min   NUMERIC(5,2)  NOT NULL,
    score_max   NUMERIC(5,2)  NOT NULL
);

INSERT INTO fin_markets.sentiment_levels (code, label, description, sort_order, score_min, score_max)
VALUES
    ('strongly_bullish',  'Strongly Bullish',  'Certainly positive',    1,  0.75,  1.00),
    ('bullish',           'Bullish',           'Likely positive',        2,  0.50,  0.75),
    ('mildly_bullish',    'Mildly Bullish',    'Somewhat positive',      3,  0.25,  0.50),
    ('slightly_bullish',  'Slightly Bullish',  'Marginally positive',    4,  0.05,  0.25),
    ('neutral',           'Neutral',           'No directional bias',    5, -0.05,  0.05),
    ('slightly_bearish',  'Slightly Bearish',  'Marginally negative',    6, -0.25, -0.05),
    ('mildly_bearish',    'Mildly Bearish',    'Somewhat negative',      7, -0.50, -0.25),
    ('bearish',           'Bearish',           'Likely negative',        8, -0.75, -0.50),
    ('strongly_bearish',  'Strongly Bearish',  'Certainly negative',     9, -1.00, -0.75)
ON CONFLICT (code) DO UPDATE SET
    label       = EXCLUDED.label,
    description = EXCLUDED.description,
    sort_order  = EXCLUDED.sort_order,
    score_min   = EXCLUDED.score_min,
    score_max   = EXCLUDED.score_max;

-- ---------------------------------------------------------------------------
-- news_topics: top-level news domain taxonomy
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_markets.news_topics (
    code        TEXT PRIMARY KEY,
    description TEXT
);

INSERT INTO fin_markets.news_topics (code, description) VALUES
    ('Corporate',          'Company earnings, M&A, leadership changes, and corporate events'),
    ('Geopolitical',       'International relations, conflicts, sanctions, military, and political risk'),
    ('Market Structure',   'Exchange rules, liquidity, market microstructure, and trading mechanisms'),
    ('Sector & Industry',  'Sector-level trends, supply chains, and industry dynamics'),
    ('Regulatory & Legal', 'Government regulations, legal rulings, compliance, and enforcement actions'),
    ('Macroeconomic',      'GDP, inflation, employment, central bank policy, and broad economic indicators')
ON CONFLICT (code) DO UPDATE SET
    description = EXCLUDED.description;


-- Drop legacy generic statics table if it exists
DROP TABLE IF EXISTS fin_markets.statics;

-- ---------------------------------------------------------------------------
-- instrument_types: valid instrument_type codes for fin_markets.quant_stats
--   code        → instrument type key (e.g. 'equity', 'crypto')
--   label       → human-readable name (e.g. 'Equity', 'Cryptocurrency')
--   description → one-line description of the instrument class
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_markets.instrument_types (
    code        TEXT    PRIMARY KEY,
    label       TEXT    NOT NULL,
    description TEXT
);

INSERT INTO fin_markets.instrument_types (code, label, description)
VALUES
    ('equity',    'Equity',        'Exchange-listed stocks and ETFs (e.g. AAPL, 005930.KS)'),
    ('crypto',    'Cryptocurrency','Cryptocurrency spot pairs (e.g. BTC-USD, ETH-USD)'),
    ('commodity',       'Commodity',       'Commodity futures tickers (e.g. NG=F nat gas, CL=F crude oil)'),
    ('precious_metal', 'Precious Metal',  'Precious metal futures tickers (e.g. GC=F gold, SI=F silver)'),
    ('index',          'Index',           'Market-benchmark index tickers (e.g. ^GSPC, 000300.SS)'),
    ('futures',   'Futures',       'Dated derivative contracts with explicit contract_ticker'),
    ('options',   'Options',       'Options flow snapshots with calls/puts open interest')
ON CONFLICT (code) DO UPDATE SET
    label       = EXCLUDED.label,
    description = EXCLUDED.description;

-- ---------------------------------------------------------------------------
-- currencies: ISO 4217 currency reference data
--   code        → ISO 4217 alpha-3 currency code (e.g. 'USD')
--   name        → full currency name (e.g. 'US Dollar')
--   symbol      → display symbol (e.g. '$', '€', '¥')
--   decimals    → decimal places for display (0 for JPY, KRW, etc.)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_markets.currencies (
    code        TEXT    PRIMARY KEY,
    name        TEXT    NOT NULL,
    symbol      TEXT    NOT NULL,
    decimals    INTEGER NOT NULL DEFAULT 2
);

INSERT INTO fin_markets.currencies (code, name, symbol, decimals)
VALUES
    ('USD', 'US Dollar',              '$',    2),
    ('CAD', 'Canadian Dollar',        'CA$',  2),
    ('BRL', 'Brazilian Real',         'R$',   2),
    ('MXN', 'Mexican Peso',           '$',    2),
    ('GBP', 'British Pound',          '£',    2),
    ('EUR', 'Euro',                   '€',    2),
    ('CHF', 'Swiss Franc',            'CHF',  2),
    ('SEK', 'Swedish Krona',          'kr',   2),
    ('NOK', 'Norwegian Krone',        'kr',   2),
    ('DKK', 'Danish Krone',           'kr',   2),
    ('SAR', 'Saudi Riyal',            '﷼',    2),
    ('AED', 'UAE Dirham',             'د.إ',  2),
    ('QAR', 'Qatari Riyal',           '﷼',    2),
    ('ILS', 'Israeli Shekel',         '₪',    2),
    ('ZAR', 'South African Rand',     'R',    2),
    ('JPY', 'Japanese Yen',           '¥',    0),
    ('CNY', 'Chinese Yuan',           '¥',    2),
    ('HKD', 'Hong Kong Dollar',       'HK$',  2),
    ('TWD', 'Taiwan Dollar',          'NT$',  2),
    ('KRW', 'South Korean Won',       '₩',    0),
    ('SGD', 'Singapore Dollar',       'S$',   2),
    ('INR', 'Indian Rupee',           '₹',    2),
    ('AUD', 'Australian Dollar',      'A$',   2),
    ('NZD', 'New Zealand Dollar',     'NZ$',  2),
    ('IDR', 'Indonesian Rupiah',      'Rp',   0),
    ('MYR', 'Malaysian Ringgit',      'RM',   2),
    ('THB', 'Thai Baht',              '฿',    2),
    ('PHP', 'Philippine Peso',        '₱',    2),
    ('VND', 'Vietnamese Dong',        '₫',    0)
ON CONFLICT (code) DO UPDATE SET
    name     = EXCLUDED.name,
    symbol   = EXCLUDED.symbol,
    decimals = EXCLUDED.decimals;


-- ---------------------------------------------------------------------------
-- macro_instruments: fixed-universe instruments for macro analysis nodes
--   code          → short identifier (e.g. 'gold', 'sofr_3m')
--   symbol        → yfinance / provider ticker (e.g. 'GC=F', 'SR3=F')
--   label         → human-readable name (e.g. 'Gold', 'SOFR 3-Month')
--   category      → 'macro' (commodities) | 'market_index' (rate/benchmark indices)
--   currency_code → ISO 4217 FK to fin_markets.currencies(code)
--   zone          → geographic zone: 'global' | 'amer' | 'emea' | 'apac'
--   sort_order    → display / iteration order within the category
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_markets.macro_instruments (
    code          TEXT    PRIMARY KEY,
    symbol        TEXT    NOT NULL,
    label         TEXT    NOT NULL,
    category      TEXT    NOT NULL CHECK (category IN ('macro', 'market_index')),
    currency_code TEXT    REFERENCES fin_markets.currencies (code),
    zone          TEXT    NOT NULL DEFAULT 'global' CHECK (zone IN ('global','amer','emea','apac')),
    sort_order    INTEGER NOT NULL DEFAULT 0
);

INSERT INTO fin_markets.macro_instruments
    (code, symbol, label, category, currency_code, zone, sort_order)
VALUES
    ('gold',    'GC=F',  'Gold',                 'macro',        'USD', 'global', 1),
    ('silver',  'SI=F',  'Silver',               'macro',        'USD', 'global', 2),
    ('nat_gas', 'NG=F',  'Natural Gas',          'macro',        'USD', 'global', 3),
    ('oil',     'CL=F',  'Crude Oil (WTI)',      'macro',        'USD', 'global', 4),
    ('bitcoin', 'BTC-USD','Bitcoin',             'macro',        'USD', 'global', 5),
    ('ethereum','ETH-USD','Ethereum',            'macro',        'USD', 'global', 6),
    ('sofr_3m', 'SR3=F', 'SOFR 3-Month Futures', 'market_index', 'USD', 'amer',   1)
ON CONFLICT (code) DO UPDATE SET
    symbol        = EXCLUDED.symbol,
    label         = EXCLUDED.label,
    category      = EXCLUDED.category,
    currency_code = EXCLUDED.currency_code,
    zone          = EXCLUDED.zone,
    sort_order    = EXCLUDED.sort_order;

-- ---------------------------------------------------------------------------
-- market_indexes: major benchmark stock-market indexes
--   code              → short identifier (e.g. 'SP500', 'HANG_SENG', 'CSI_300')
--   name              → human-readable index name
--   ticker            → Yahoo Finance ticker for the index (e.g. '^GSPC', '^HSI')
--   currency_code     → ISO 4217 FK; the traded currency for stocks in this index
--   stats_provider    → provider to use when fetching OHLCV for stocks in this index
--   zone              → geographic zone: 'amer' | 'emea' | 'apac'
--   yf_exchange_codes → yfinance info['exchange'] values for stocks in this index
--   sort_order        → priority when multiple indexes share exchange codes (lower = higher priority)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_markets.market_indexes (
    code              TEXT      PRIMARY KEY,
    name              TEXT      NOT NULL,
    ticker            TEXT,
    currency_code     TEXT      NOT NULL REFERENCES fin_markets.currencies(code),
    stats_provider    TEXT      NOT NULL DEFAULT 'fmp',
    zone              TEXT      NOT NULL CHECK (zone IN ('amer','emea','apac')),
    yf_exchange_codes TEXT[]    NOT NULL DEFAULT '{}',
    sort_order        INTEGER   NOT NULL DEFAULT 0
);

-- Seed data (idempotent) — covers the major benchmark indexes used for
-- stock index membership detection and currency derivation.
-- yf_exchange_codes: codes that yfinance returns in ticker.info['exchange']
--   for stocks listed on the exchanges that constitute each index.
INSERT INTO fin_markets.market_indexes
    (code, name, ticker, currency_code, stats_provider, zone, yf_exchange_codes, sort_order)
VALUES
-- ── Americas ────────────────────────────────────────────────────────────────
('SP500',       'S&P 500',           '^GSPC',   'USD', 'fmp',      'amer', ARRAY['NMS','NGM','NCM','NYQ','PCX','ASE','BTS','NYS'], 1),
('NASDAQ_100',  'Nasdaq 100',        '^NDX',    'USD', 'fmp',      'amer', ARRAY['NMS','NGM','NCM'],                               2),
('DOW_JONES',   'Dow Jones',         '^DJI',    'USD', 'fmp',      'amer', ARRAY['NMS','NYQ','NGM'],                               3),
('RUSSELL_2000','Russell 2000',      '^RUT',    'USD', 'fmp',      'amer', ARRAY['NMS','NGM','NCM','NYQ','PCX','ASE','BTS'],        4),
('TSX',         'S&P/TSX Composite', '^GSPTSE', 'CAD', 'yfinance', 'amer', ARRAY['TOR'],                                           5),
('IBOVESPA',    'Ibovespa',          '^BVSP',   'BRL', 'yfinance', 'amer', ARRAY['SAO'],                                           6),
-- ── Asia-Pacific ────────────────────────────────────────────────────────────
('HANG_SENG',   'Hang Seng',         '^HSI',    'HKD', 'fmp',      'apac', ARRAY['HKG'],                                           1),
('CSI_300',     'CSI 300',           '000300.SS','CNY','yfinance', 'apac', ARRAY['SHH','SHZ'],                                     2),
('NIKKEI_225',  'Nikkei 225',        '^N225',   'JPY', 'yfinance', 'apac', ARRAY['TYO','OSA','JPX'],                               3),
('TOPIX',       'TOPIX',             '^TOPX',   'JPY', 'yfinance', 'apac', ARRAY['TYO','OSA','JPX'],                               4),
('KOSPI',       'KOSPI',             '^KS11',   'KRW', 'yfinance', 'apac', ARRAY['KSC'],                                           5),
('KOSDAQ',      'KOSDAQ',            '^KQ11',   'KRW', 'yfinance', 'apac', ARRAY['KSQ'],                                           6),
('ASX_200',     'ASX 200',           '^AXJO',   'AUD', 'yfinance', 'apac', ARRAY['ASX'],                                           7),
('TAIEX',       'TAIEX',             '^TWII',   'TWD', 'yfinance', 'apac', ARRAY['TAI','TWO'],                                     8),
('STI',         'STI',               '^STI',    'SGD', 'yfinance', 'apac', ARRAY['SGX','SES'],                                     9),
('NIFTY_50',    'Nifty 50',          '^NSEI',   'INR', 'yfinance', 'apac', ARRAY['NSI','NSE','BSE','BOM'],                        10),
('SENSEX',      'BSE Sensex',        '^BSESN',  'INR', 'yfinance', 'apac', ARRAY['BSE','BOM'],                                    11),
-- ── EMEA ────────────────────────────────────────────────────────────────────
('FTSE_100',    'FTSE 100',          '^FTSE',   'GBP', 'fmp',      'emea', ARRAY['LSE','IOB'],                                     1),
('DAX',         'DAX',               '^GDAXI',  'EUR', 'fmp',      'emea', ARRAY['FRA','GER','XETRA','ETR'],                       2),
('CAC_40',      'CAC 40',            '^FCHI',   'EUR', 'fmp',      'emea', ARRAY['PAR','ENX'],                                     3),
('SMI',         'SMI',               '^SSMI',   'CHF', 'yfinance', 'emea', ARRAY['SWX','EBS'],                                     4),
('AEX',         'AEX',               '^AEX',    'EUR', 'yfinance', 'emea', ARRAY['AMS'],                                           5),
('MIB',         'FTSE MIB',          '^FTSEMIB','EUR', 'yfinance', 'emea', ARRAY['MIL'],                                           6),
('IBEX_35',     'IBEX 35',           '^IBEX',   'EUR', 'yfinance', 'emea', ARRAY['MCE'],                                           7),
('TADAWUL',     'Tadawul All Share',  '^TASI.SR','SAR', 'yfinance', 'emea', ARRAY['SAU'],                                          8)
ON CONFLICT (code) DO UPDATE SET
    name              = EXCLUDED.name,
    ticker            = EXCLUDED.ticker,
    currency_code     = EXCLUDED.currency_code,
    stats_provider    = EXCLUDED.stats_provider,
    zone              = EXCLUDED.zone,
    yf_exchange_codes = EXCLUDED.yf_exchange_codes,
    sort_order        = EXCLUDED.sort_order;

