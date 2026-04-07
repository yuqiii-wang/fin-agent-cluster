CREATE SCHEMA IF NOT EXISTS fin_markets;

-- ============================================================
-- fin_markets.sentiment_level
-- ============================================================
DO $$ BEGIN
    CREATE TYPE fin_markets.sentiment_level AS ENUM (
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
-- Centralized constant lookup table
-- Covers all fin_markets controlled-vocabulary types (TEXT columns
-- validated via fin_markets.is_enum()).  sentiment_level remains a
-- native PostgreSQL ENUM type for performance on heavily-queried cols.
-- Run this AFTER fin_markets_0_consts.sql (schema must exist).
-- Columns:
--   id          serial PK
--   type        enum type name   (e.g. 'security_type')
--   subtype     grouping label   (populated where SQL comments define groups)
--   short_value acronym / code   (e.g. 'EQUITY', 'USD') — PK for is_enum()
--   long_value  expanded name    (e.g. 'US Dollar') — NULL when short_value is self-explanatory
--   description additional info  (e.g. 'common stock') — NULL when not needed
-- ============================================================

CREATE TABLE IF NOT EXISTS fin_markets.enum_const (
    id          SERIAL  PRIMARY KEY,
    type        TEXT    NOT NULL,
    subtype     TEXT,
    short_value       TEXT    NOT NULL,
    long_value       TEXT,
    description TEXT,
    UNIQUE (type, short_value)
);

-- ============================================================
-- security_type
-- ============================================================
INSERT INTO fin_markets.enum_const (type, subtype, short_value, long_value, description) VALUES
    ('security_type', NULL, 'EQUITY', NULL, 'common stock'),
    ('security_type', NULL, 'PREFERRED_STOCK', NULL, 'preferred shares'),
    ('security_type', NULL, 'ETF', NULL, 'exchange-traded fund'),
    ('security_type', NULL, 'BOND', NULL, 'generic bond'),
    ('security_type', NULL, 'CORPORATE_BOND', NULL, 'corporate debt'),
    ('security_type', NULL, 'TREASURY', NULL, 'government / sovereign bond'),
    ('security_type', NULL, 'MUNICIPAL_BOND', NULL, 'municipal debt'),
    ('security_type', NULL, 'MORTGAGE_BACKED', NULL, 'MBS / ABS'),
    ('security_type', NULL, 'CONVERTIBLE', NULL, 'convertible bond / note'),
    ('security_type', NULL, 'FUTURE', NULL, 'futures contract'),
    ('security_type', NULL, 'OPTION', NULL, 'option contract'),
    ('security_type', NULL, 'SWAP', NULL, 'interest-rate / credit swap'),
    ('security_type', NULL, 'CFD', NULL, 'contract for difference'),
    ('security_type', NULL, 'INDEX', NULL, 'market index'),
    ('security_type', NULL, 'FX', NULL, 'foreign exchange pair'),
    ('security_type', NULL, 'CRYPTO', NULL, 'cryptocurrency'),
    ('security_type', NULL, 'COMMODITY', NULL, 'physical commodity'),
    ('security_type', NULL, 'FUND', NULL, 'mutual fund / UCITS'),
    ('security_type', NULL, 'REIT', NULL, 'real-estate investment trust'),
    ('security_type', NULL, 'MLP', NULL, 'master limited partnership'),
    ('security_type', NULL, 'SPAC', NULL, 'special-purpose acquisition co.'),
    ('security_type', NULL, 'WARRANT', NULL, 'warrant'),
    ('security_type', NULL, 'RIGHTS', NULL, 'subscription rights'),
    ('security_type', NULL, 'UNIT', NULL, 'unit (bundle of securities)'),
    ('security_type', NULL, 'ADR', NULL, 'American depositary receipt'),
    ('security_type', NULL, 'GDR', NULL, 'Global depositary receipt'),
    ('security_type', NULL, 'STRUCTURED_PRODUCT', NULL, 'structured note / certificate'),
    ('security_type', NULL, 'MONEY_MARKET', NULL, 'money-market instrument'),
    ('security_type', NULL, 'OTHER', NULL, NULL)
ON CONFLICT (type, short_value) DO NOTHING;

-- ============================================================
-- trade_interval
-- ============================================================
INSERT INTO fin_markets.enum_const (type, subtype, short_value, long_value, description) VALUES
    ('trade_interval', NULL, 'tick', 'individual tick', NULL),
    ('trade_interval', NULL, '1s',   '1-second bar', NULL),
    ('trade_interval', NULL, '10s',  '10-second bar', NULL),
    ('trade_interval', NULL, '1m',   '1-minute bar', NULL),
    ('trade_interval', NULL, '5m',   '5-minute bar', NULL),
    ('trade_interval', NULL, '10m',  '10-minute bar', NULL),
    ('trade_interval', NULL, '15m',  '15-minute bar', NULL),
    ('trade_interval', NULL, '30m',  '30-minute bar', NULL),
    ('trade_interval', NULL, '1h',   '1-hour bar', NULL),
    ('trade_interval', NULL, '4h',   '4-hour bar', NULL),
    ('trade_interval', NULL, '1d',   'daily bar', NULL),
    ('trade_interval', NULL, '1w',   'weekly bar', NULL),
    ('trade_interval', NULL, '1mo',  'monthly bar', NULL),
    ('trade_interval', NULL, '1q',   'quarterly bar', NULL),
    ('trade_interval', NULL, '1y',   'yearly bar', NULL)
ON CONFLICT (type, short_value) DO NOTHING;

-- ============================================================
-- major_institution  (exchanges, CCPs, major data venues)
-- ============================================================
INSERT INTO fin_markets.enum_const (type, short_value, long_value, description) VALUES
    ('major_institution', 'NASDAQ',    'NASDAQ Stock Market',              'US equities – National Market System'),
    ('major_institution', 'NMS',       'NASDAQ NMS',                       'NASDAQ National Market System (Yahoo Finance code)'),
    ('major_institution', 'NGM',       'NASDAQ Global Market',             'NASDAQ Global Market tier'),
    ('major_institution', 'NCM',       'NASDAQ Capital Market',            'NASDAQ Capital Market tier'),
    ('major_institution', 'NYSE',      'New York Stock Exchange',          'US equities'),
    ('major_institution', 'AMEX',      'NYSE American (AMEX)',             'US equities'),
    ('major_institution', 'BATS',      'Cboe BZX Exchange',                'US equities'),
    ('major_institution', 'OTC',       'OTC Markets',                      'OTC US equities'),
    ('major_institution', 'PINK',      'OTC Pink Sheets',                  'Penny / pink sheet stocks'),
    ('major_institution', 'TSX',       'Toronto Stock Exchange',           'Canadian equities'),
    ('major_institution', 'LSE',       'London Stock Exchange',            'UK equities'),
    ('major_institution', 'EURONEXT',  'Euronext',                         'European equities'),
    ('major_institution', 'XETRA',     'Deutsche Boerse XETRA',            'German equities'),
    ('major_institution', 'BIT',       'Borsa Italiana',                   'Italian equities'),
    ('major_institution', 'HKEX',      'Hong Kong Stock Exchange',         'HK equities'),
    ('major_institution', 'TSE',       'Tokyo Stock Exchange',             'Japanese equities'),
    ('major_institution', 'KRX',       'Korea Exchange',                   'Korean equities'),
    ('major_institution', 'SSE',       'Shanghai Stock Exchange',          'Chinese A-shares'),
    ('major_institution', 'SZSE',      'Shenzhen Stock Exchange',          'Chinese A-shares'),
    ('major_institution', 'ASX',       'Australian Securities Exchange',   'Australian equities'),
    ('major_institution', 'BSE',       'Bombay Stock Exchange',            'Indian equities'),
    ('major_institution', 'NSE',       'National Stock Exchange India',    'Indian equities'),
    ('major_institution', 'SGX',       'Singapore Exchange',               'Singapore equities'),
    ('major_institution', 'OB',        'Oslo Bors',                        'Norwegian equities'),
    ('major_institution', 'OSE',       'Oslo Stock Exchange',              'Norwegian equities (alt code)'),
    ('major_institution', 'SIX',       'SIX Swiss Exchange',               'Swiss equities'),
    ('major_institution', 'CBOE',      'Cboe Global Markets',              'Options/derivatives exchange'),
    ('major_institution', 'CME',       'Chicago Mercantile Exchange',      'Futures/derivatives'),
    ('major_institution', 'ICE',       'Intercontinental Exchange',        'Multi-asset exchange'),
    ('major_institution', 'NYMEX',     'New York Mercantile Exchange',     'Energy futures'),
    ('major_institution', 'COMEX',     'COMEX (Metals)',                   'Metals futures'),
    ('major_institution', 'BINANCE',   'Binance',                          'Crypto exchange'),
    ('major_institution', 'COINBASE',  'Coinbase',                         'Crypto exchange')
ON CONFLICT (type, short_value) DO NOTHING;

-- ============================================================
-- entity_type
-- ============================================================
INSERT INTO fin_markets.enum_const (type, subtype, short_value, long_value, description) VALUES
    ('entity_type', NULL, 'COMPANY', NULL, 'operating corporation'),
    ('entity_type', NULL, 'BANK', NULL, 'commercial / investment bank'),
    ('entity_type', NULL, 'CENTRAL_BANK', NULL, 'central / reserve bank'),
    ('entity_type', NULL, 'BROKER', NULL, 'broker-dealer'),
    ('entity_type', NULL, 'EXCHANGE', NULL, 'securities / derivatives exchange'),
    ('entity_type', NULL, 'CLEARING_HOUSE', NULL, 'CCP / clearing corp'),
    ('entity_type', NULL, 'DEPOSITORY', NULL, 'CSD / depository (DTCC, Euroclear)'),
    ('entity_type', NULL, 'CUSTODIAN', NULL, 'asset custodian'),
    ('entity_type', NULL, 'FUND', NULL, 'mutual fund / UCITS'),
    ('entity_type', NULL, 'HEDGE_FUND', NULL, 'hedge fund'),
    ('entity_type', NULL, 'PE_FIRM', NULL, 'private equity firm'),
    ('entity_type', NULL, 'VC_FIRM', NULL, 'venture capital firm'),
    ('entity_type', NULL, 'FAMILY_OFFICE', NULL, 'single / multi-family office'),
    ('entity_type', NULL, 'SOVEREIGN_FUND', NULL, 'sovereign wealth fund'),
    ('entity_type', NULL, 'PENSION', NULL, 'pension / superannuation fund'),
    ('entity_type', NULL, 'ENDOWMENT', NULL, 'endowment / foundation'),
    ('entity_type', NULL, 'INSURANCE', NULL, 'insurance / reinsurance'),
    ('entity_type', NULL, 'MARKET_MAKER', NULL, 'designated market maker'),
    ('entity_type', NULL, 'REGULATOR', NULL, 'securities / banking regulator'),
    ('entity_type', NULL, 'GOVERNMENT', NULL, 'government department / ministry'),
    ('entity_type', NULL, 'RATING_AGENCY', NULL, 'credit rating agency'),
    ('entity_type', NULL, 'INDEX_PROVIDER', NULL, 'index / benchmark provider'),
    ('entity_type', NULL, 'DATA_VENDOR', NULL, 'market data vendor'),
    ('entity_type', NULL, 'SPV', NULL, 'special-purpose vehicle'),
    ('entity_type', NULL, 'TRADE_ASSOCIATION', NULL, 'industry / trade body'),
    ('entity_type', NULL, 'MULTILATERAL', NULL, 'IMF, World Bank, BIS, etc.'),
    ('entity_type', NULL, 'OTHER', NULL, NULL)
ON CONFLICT (type, short_value) DO NOTHING;

-- ============================================================
-- news_category
-- ============================================================
INSERT INTO fin_markets.enum_const (type, subtype, short_value, long_value, description) VALUES
    ('news_category', NULL, 'EARNINGS', NULL, 'earnings releases, revenue & guidance'),
    ('news_category', NULL, 'M_AND_A', NULL, 'mergers & acquisitions'),
    ('news_category', NULL, 'IPO', NULL, 'IPO / direct listing / SPAC'),
    ('news_category', NULL, 'SECONDARY_OFFERING', NULL, 'follow-on / secondary offering'),
    ('news_category', NULL, 'BUYBACK', NULL, 'share repurchase'),
    ('news_category', NULL, 'DIVIDEND', NULL, 'dividend announcement / change'),
    ('news_category', NULL, 'RESTRUCTURING', NULL, 'corporate restructuring'),
    ('news_category', NULL, 'BANKRUPTCY', NULL, 'bankruptcy / insolvency'),
    ('news_category', NULL, 'REGULATION', NULL, 'regulatory action / ruling'),
    ('news_category', NULL, 'LITIGATION', NULL, 'lawsuit / settlement'),
    ('news_category', NULL, 'MACRO', NULL, 'macroeconomic data / policy'),
    ('news_category', NULL, 'CENTRAL_BANK', NULL, 'central bank decision / speech'),
    ('news_category', NULL, 'GEOPOLITICS', NULL, 'geopolitical news / conflict'),
    ('news_category', NULL, 'TRADE_POLICY', NULL, 'tariffs, trade agreements'),
    ('news_category', NULL, 'COMMODITY', NULL, 'commodity market news'),
    ('news_category', NULL, 'FX', NULL, 'foreign exchange / currency'),
    ('news_category', NULL, 'CRYPTO', NULL, 'cryptocurrency / digital asset'),
    ('news_category', NULL, 'ESG', NULL, 'environmental, social, governance'),
    ('news_category', NULL, 'TECHNOLOGY', NULL, 'tech / product / innovation'),
    ('news_category', NULL, 'LABOR', NULL, 'labor market / strikes / hiring'),
    ('news_category', NULL, 'REAL_ESTATE', NULL, 'real estate / housing market'),
    ('news_category', NULL, 'RATING_CHANGE', NULL, 'credit rating upgrade / downgrade'),
    ('news_category', NULL, 'ANALYST', NULL, 'analyst initiation / revision'),
    ('news_category', NULL, 'INSIDER', NULL, 'insider trading / filing'),
    ('news_category', NULL, 'MARKET_STRUCTURE', NULL, 'market microstructure / exchange'),
    ('news_category', NULL, 'OPINION', NULL, 'editorial / opinion / commentary'),
    ('news_category', NULL, 'RESEARCH', NULL, 'research report / white paper'),
    ('news_category', NULL, 'OTHER', NULL, NULL)
ON CONFLICT (type, short_value) DO NOTHING;

-- ============================================================
-- region
-- ============================================================
INSERT INTO fin_markets.enum_const (type, subtype, short_value, long_value, description) VALUES
    ('region', 'AMER', 'United States', NULL, NULL),
    ('region', 'APAC', 'China', NULL, NULL),
    ('region', 'APAC', 'Japan', NULL, NULL),
    ('region', 'EMEA', 'Germany', NULL, NULL),
    ('region', 'EMEA', 'United Kingdom', NULL, NULL),
    ('region', 'EMEA', 'France', NULL, NULL),
    ('region', 'APAC', 'India', NULL, NULL),
    ('region', 'EMEA', 'Italy', NULL, NULL),
    ('region', 'AMER', 'Brazil', NULL, NULL),
    ('region', 'AMER', 'Canada', NULL, NULL),
    ('region', 'APAC', 'South Korea', NULL, NULL),
    ('region', 'EMEA', 'Russia', NULL, NULL),
    ('region', 'APAC', 'Australia', NULL, NULL),
    ('region', 'AMER', 'Mexico', NULL, NULL),
    ('region', 'APAC', 'Indonesia', NULL, NULL),
    ('region', 'EMEA', 'Netherlands', NULL, NULL),
    ('region', 'EMEA', 'Saudi Arabia', NULL, NULL),
    ('region', 'EMEA', 'Turkey', NULL, NULL),
    ('region', 'EMEA', 'Switzerland', NULL, NULL),
    ('region', 'AMER', 'Argentina', NULL, NULL),
    ('region', 'EMEA', 'South Africa', NULL, NULL),
    ('region', 'APAC', 'Singapore', NULL, NULL),
    ('region', 'APAC', 'Hong Kong', NULL, NULL),
    ('region', 'EMEA', 'Sweden', NULL, NULL),
    ('region', 'EMEA', 'Norway', NULL, NULL),
    ('region', NULL,   'Global', NULL, 'worldwide / multi-economy')
ON CONFLICT (type, short_value) DO NOTHING;

-- ============================================================
-- currency
-- ============================================================
INSERT INTO fin_markets.enum_const (type, subtype, short_value, long_value, description) VALUES
    ('currency', NULL, 'USD',  'US Dollar', NULL),
    ('currency', NULL, 'EUR',  'Euro', NULL),
    ('currency', NULL, 'JPY',  'Japanese Yen', NULL),
    ('currency', NULL, 'GBP',  'British Pound Sterling', NULL),
    ('currency', NULL, 'CNY',  'Chinese Yuan Renminbi (onshore)', NULL),
    ('currency', NULL, 'CNH',  'Chinese Yuan Renminbi (offshore)', NULL),
    ('currency', NULL, 'RMB',  'Renminbi (generic label)', NULL),
    ('currency', NULL, 'INR',  'Indian Rupee', NULL),
    ('currency', NULL, 'BRL',  'Brazilian Real', NULL),
    ('currency', NULL, 'CAD',  'Canadian Dollar', NULL),
    ('currency', NULL, 'KRW',  'South Korean Won', NULL),
    ('currency', NULL, 'RUB',  'Russian Ruble', NULL),
    ('currency', NULL, 'AUD',  'Australian Dollar', NULL),
    ('currency', NULL, 'MXN',  'Mexican Peso', NULL),
    ('currency', NULL, 'IDR',  'Indonesian Rupiah', NULL),
    ('currency', NULL, 'SAR',  'Saudi Riyal', NULL),
    ('currency', NULL, 'TRY',  'Turkish Lira', NULL),
    ('currency', NULL, 'CHF',  'Swiss Franc', NULL),
    ('currency', NULL, 'ARS',  'Argentine Peso', NULL),
    ('currency', NULL, 'ZAR',  'South African Rand', NULL),
    ('currency', NULL, 'SGD',  'Singapore Dollar', NULL),
    ('currency', NULL, 'HKD',  'Hong Kong Dollar', NULL),
    ('currency', NULL, 'SEK',  'Swedish Krona', NULL),
    ('currency', NULL, 'NOK',  'Norwegian Krone', NULL),
    ('currency', NULL, 'DKK',  'Danish Krone', NULL),
    ('currency', NULL, 'PLN',  'Polish Zloty', NULL),
    ('currency', NULL, 'CZK',  'Czech Koruna', NULL),
    ('currency', NULL, 'HUF',  'Hungarian Forint', NULL),
    ('currency', NULL, 'ILS',  'Israeli New Shekel', NULL),
    ('currency', NULL, 'AED',  'UAE Dirham', NULL),
    ('currency', NULL, 'QAR',  'Qatari Riyal', NULL),
    ('currency', NULL, 'KWD',  'Kuwaiti Dinar', NULL),
    ('currency', NULL, 'THB',  'Thai Baht', NULL),
    ('currency', NULL, 'MYR',  'Malaysian Ringgit', NULL),
    ('currency', NULL, 'PHP',  'Philippine Peso', NULL),
    ('currency', NULL, 'VND',  'Vietnamese Dong', NULL),
    ('currency', NULL, 'TWD',  'New Taiwan Dollar', NULL),
    ('currency', NULL, 'NZD',  'New Zealand Dollar', NULL),
    ('currency', NULL, 'BTC',  'Bitcoin', NULL),
    ('currency', NULL, 'ETH',  'Ethereum', NULL),
    ('currency', NULL, 'USDT', 'Tether (stablecoin)', NULL),
    ('currency', NULL, 'OTHER','unknown / unlisted currency', NULL),
    ('currency', NULL, 'N/A',  'not applicable (e.g. index, ratio)', NULL)
ON CONFLICT (type, short_value) DO NOTHING;

-- ============================================================
-- dividend_frequency
-- ============================================================
INSERT INTO fin_markets.enum_const (type, subtype, short_value, long_value, description) VALUES
    ('dividend_frequency', NULL, 'WEEKLY', NULL, 'weekly distribution (rare, some money-market)'),
    ('dividend_frequency', NULL, 'BI_WEEKLY', NULL, 'every two weeks'),
    ('dividend_frequency', NULL, 'MONTHLY', NULL, 'monthly'),
    ('dividend_frequency', NULL, 'BI_MONTHLY', NULL, 'every two months'),
    ('dividend_frequency', NULL, 'QUARTERLY', NULL, 'quarterly'),
    ('dividend_frequency', NULL, 'SEMI_ANNUAL', NULL, 'semi-annual / half-yearly'),
    ('dividend_frequency', NULL, 'ANNUAL', NULL, 'annual'),
    ('dividend_frequency', NULL, 'IRREGULAR', NULL, 'irregular / special'),
    ('dividend_frequency', NULL, 'VARIABLE', NULL, 'variable schedule'),
    ('dividend_frequency', NULL, 'NONE', NULL, 'no dividend')
ON CONFLICT (type, short_value) DO NOTHING;

-- ============================================================
-- action_type  (subtype = action category)
-- ============================================================
INSERT INTO fin_markets.enum_const (type, subtype, short_value, long_value, description) VALUES
    ('action_type', 'Monetary policy',              'RATE_DECISION', NULL, 'interest-rate decision'),
    ('action_type', 'Monetary policy',              'RATE_GUIDANCE', NULL, 'forward guidance on rates'),
    ('action_type', 'Monetary policy',              'QE_QT', NULL, 'quantitative easing / tightening'),
    ('action_type', 'Monetary policy',              'RESERVE_CHANGE', NULL, 'reserve requirement change'),
    ('action_type', 'Monetary policy',              'LENDING_FACILITY', NULL, 'standing facility / discount window'),
    ('action_type', 'Monetary policy',              'YIELD_CURVE_CONTROL', NULL, 'yield-curve control adjustment'),
    ('action_type', 'Market operations',            'FX_INTERVENTION', NULL, 'currency intervention'),
    ('action_type', 'Market operations',            'COMMODITY_PURCHASE', NULL, 'strategic reserve purchase'),
    ('action_type', 'Market operations',            'COMMODITY_SALE', NULL, 'strategic reserve sale'),
    ('action_type', 'Market operations',            'EQUITY_PURCHASE', NULL, 'equity / ETF purchase program'),
    ('action_type', 'Market operations',            'EQUITY_SALE', NULL, 'equity divestiture'),
    ('action_type', 'Market operations',            'BOND_PURCHASE', NULL, 'bond buying program'),
    ('action_type', 'Market operations',            'BOND_SALE', NULL, 'bond selling / unwinding'),
    ('action_type', 'Market operations',            'BLOCK_TRADE', NULL, 'large block trade / crosses'),
    ('action_type', 'Regulatory / policy',          'MARGIN_CHANGE', NULL, 'margin / collateral requirement'),
    ('action_type', 'Regulatory / policy',          'CAPITAL_CONTROL', NULL, 'capital flow restriction'),
    ('action_type', 'Regulatory / policy',          'SANCTION', NULL, 'economic / financial sanction'),
    ('action_type', 'Regulatory / policy',          'TARIFF', NULL, 'trade tariff / duty'),
    ('action_type', 'Regulatory / policy',          'POLICY', NULL, 'general policy announcement'),
    ('action_type', 'Regulatory / policy',          'REGULATION', NULL, 'new rule / directive'),
    ('action_type', 'Regulatory / policy',          'LISTING_APPROVAL', NULL, 'IPO / listing approval'),
    ('action_type', 'Regulatory / policy',          'DELISTING', NULL, 'forced delisting / suspension'),
    ('action_type', 'Regulatory / policy',          'BAILOUT', NULL, 'financial rescue / bailout'),
    ('action_type', 'Regulatory / policy',          'STRESS_TEST', NULL, 'bank / system stress test result'),
    ('action_type', 'Corporate-level institutional','SHARE_BUYBACK', NULL, 'share repurchase program'),
    ('action_type', 'Corporate-level institutional','DIVIDEND_POLICY', NULL, 'dividend policy change'),
    ('action_type', 'Corporate-level institutional','EARNINGS_GUIDANCE', NULL, 'corporate earnings / revenue guidance'),
    ('action_type', 'Corporate-level institutional','MERGER_ACQUISITION', NULL, 'M&A announcement'),
    ('action_type', 'Corporate-level institutional','STAKE_CHANGE', NULL, 'significant stake acquisition / disposal'),
    ('action_type', NULL,                           'OTHER', NULL, NULL)
ON CONFLICT (type, short_value) DO NOTHING;

-- ============================================================
-- industry
-- ============================================================
INSERT INTO fin_markets.enum_const (type, subtype, short_value, long_value, description) VALUES
    ('industry', NULL, 'ENERGY', NULL, NULL),
    ('industry', NULL, 'MATERIALS', NULL, NULL),
    ('industry', NULL, 'INDUSTRIALS', NULL, NULL),
    ('industry', NULL, 'CONSUMER_DISCRETIONARY', NULL, NULL),
    ('industry', NULL, 'CONSUMER_STAPLES', NULL, NULL),
    ('industry', NULL, 'HEALTH_CARE', NULL, NULL),
    ('industry', NULL, 'FINANCIALS', NULL, NULL),
    ('industry', NULL, 'INFORMATION_TECHNOLOGY', NULL, NULL),
    ('industry', NULL, 'COMMUNICATION_SERVICES', NULL, NULL),
    ('industry', NULL, 'UTILITIES', NULL, NULL),
    ('industry', NULL, 'REAL_ESTATE', NULL, NULL)
ON CONFLICT (type, short_value) DO NOTHING;

-- ============================================================
-- data_source
-- Subtypes: Market Data | Official / Gov | Crypto Exchange |
--           Social Media | Traditional Media | Internal
-- ============================================================
INSERT INTO fin_markets.enum_const (type, subtype, short_value, long_value, description) VALUES
    -- Market Data vendors
    ('data_source', 'Market Data', 'YAHOO',               'Yahoo Finance', NULL),
    ('data_source', 'Market Data', 'POLYGON',             'Polygon.io', NULL),
    ('data_source', 'Market Data', 'BLOOMBERG',           'Bloomberg Terminal / B-PIPE', NULL),
    ('data_source', 'Market Data', 'REFINITIV',           'Refinitiv (LSEG) / Eikon', NULL),
    ('data_source', 'Market Data', 'ALPHAVANTAGE',        'Alpha Vantage', NULL),
    ('data_source', 'Market Data', 'QUANDL',              'Nasdaq Data Link (Quandl)', NULL),
    ('data_source', 'Market Data', 'IEX',                 'IEX Cloud', NULL),
    ('data_source', 'Market Data', 'FINNHUB',             'Finnhub', NULL),
    ('data_source', 'Market Data', 'TIINGO',              'Tiingo', NULL),
    ('data_source', 'Market Data', 'CME',                 'CME Group', NULL),
    ('data_source', 'Market Data', 'SEC_EDGAR',           'SEC EDGAR filings', NULL),
    ('data_source', 'Market Data', 'POLYMARKET',           'Polymarket', NULL),
    -- Official / Government data
    ('data_source', 'Official / Gov', 'FRED',             'Federal Reserve (FRED)', NULL),
    ('data_source', 'Official / Gov', 'WORLD_BANK',       'World Bank Open Data', NULL),
    ('data_source', 'Official / Gov', 'IMF',              'IMF data', NULL),
    ('data_source', 'Official / Gov', 'EUROSTAT',         'Eurostat', NULL),
    -- Crypto exchanges
    ('data_source', 'Crypto Exchange', 'BINANCE',         'Binance', NULL),
    ('data_source', 'Crypto Exchange', 'COINBASE',        'Coinbase', NULL),
    -- Social media / KOL platforms
    ('data_source', 'Social Media', 'X_TWITTER',          'X (Twitter)', 'posts, threads, KOL commentary'),
    ('data_source', 'Social Media', 'REDDIT',             'Reddit', 'r/wallstreetbets and finance subreddits'),
    ('data_source', 'Social Media', 'TIKTOK',             'TikTok', 'short-video financial influencer content'),
    ('data_source', 'Social Media', 'ZHIHU',              'Zhihu (知乎)', 'Chinese Q&A / opinion platform'),
    ('data_source', 'Social Media', 'WEIBO',              'Weibo (微博)', 'Chinese microblogging / KOL posts'),
    ('data_source', 'Social Media', 'WECHAT',             'WeChat (微信)', 'WeChat public accounts / moments'),
    ('data_source', 'Social Media', 'LINKEDIN',           'LinkedIn', 'professional network posts & articles'),
    ('data_source', 'Social Media', 'YOUTUBE',            'YouTube', 'financial video commentary / podcasts'),
    ('data_source', 'Social Media', 'STOCKTWITS',         'StockTwits', 'real-time trader sentiment stream'),
    ('data_source', 'Social Media', 'TELEGRAM',           'Telegram', 'financial channels & signal groups'),
    ('data_source', 'Social Media', 'DISCORD',            'Discord', 'retail trading communities'),
    -- Traditional prestige media
    ('data_source', 'Traditional Media', 'REUTERS',       'Reuters', NULL),
    ('data_source', 'Traditional Media', 'AP',            'Associated Press', NULL),
    ('data_source', 'Traditional Media', 'WSJ',           'The Wall Street Journal', NULL),
    ('data_source', 'Traditional Media', 'FT',            'Financial Times', NULL),
    ('data_source', 'Traditional Media', 'NYT',           'The New York Times', NULL),
    ('data_source', 'Traditional Media', 'ECONOMIST',     'The Economist', NULL),
    ('data_source', 'Traditional Media', 'CNBC',          'CNBC', NULL),
    ('data_source', 'Traditional Media', 'BLOOMBERG_NEWS','Bloomberg News (editorial)', 'distinct from Bloomberg Terminal data feed'),
    ('data_source', 'Traditional Media', 'BARRONS',       'Barron''s', NULL),
    ('data_source', 'Traditional Media', 'FORBES',        'Forbes', NULL),
    ('data_source', 'Traditional Media', 'FORTUNE',       'Fortune', NULL),
    ('data_source', 'Traditional Media', 'CAIXIN',        'Caixin (财新)', 'Chinese financial investigative media'),
    ('data_source', 'Traditional Media', 'NIKKEI',        'Nikkei Asia', NULL),
    ('data_source', 'Traditional Media', 'SEEKING_ALPHA', 'Seeking Alpha', 'financial analysis & opinion platform'),
    -- Internal / derived
    ('data_source', 'Internal', 'MANUAL',                 'manually entered', NULL),
    ('data_source', 'Internal', 'COMPUTED',               'internally computed / derived', NULL),
    ('data_source', 'Internal', 'GENERIC_WEB_SUMMARY',    'AI / LLM generated from web search', NULL),
    ('data_source', NULL,        'OTHER',                  NULL, NULL)
ON CONFLICT (type, short_value) DO NOTHING;

-- ============================================================
-- relationship_type  (subtype = relationship category)
-- ============================================================
INSERT INTO fin_markets.enum_const (type, subtype, short_value, long_value, description) VALUES
    ('relationship_type', 'Index / benchmark membership',   'INDEX_CONSTITUENT', NULL, 'constituent of an index (e.g. S&P 500 member)'),
    ('relationship_type', 'Index / benchmark membership',   'BENCHMARK', NULL, 'benchmark / reference security for another'),
    ('relationship_type', 'Market-structure dominance',     'OLIGOPOLY_MEMBER', NULL, 'collective market-share leaders (e.g. big-4 banks in AU)'),
    ('relationship_type', 'Market-structure dominance',     'SECTOR_LEADER', NULL, 'recognised sector leader / bellwether'),
    ('relationship_type', 'Market-structure dominance',     'MARKET_LEADER', NULL, 'dominant player in its end-market'),
    ('relationship_type', 'Competitive / commercial',       'PEER', NULL, 'direct industry peer / competitor'),
    ('relationship_type', 'Competitive / commercial',       'SUPPLIER', NULL, 'upstream supplier in supply chain'),
    ('relationship_type', 'Competitive / commercial',       'CUSTOMER', NULL, 'downstream customer in supply chain'),
    ('relationship_type', 'Competitive / commercial',       'STRATEGIC_PARTNER', NULL, 'formal strategic partnership / alliance'),
    ('relationship_type', 'Competitive / commercial',       'LICENSEE', NULL, 'licensee of IP / brand from the other'),
    ('relationship_type', 'Competitive / commercial',       'LICENSOR', NULL, 'licensor of IP / brand to the other'),
    ('relationship_type', 'Competitive / commercial',       'FRANCHISE', NULL, 'franchisor–franchisee relationship'),
    ('relationship_type', 'Corporate structure',            'PARENT', NULL, 'parent / holding company'),
    ('relationship_type', 'Corporate structure',            'SUBSIDIARY', NULL, 'subsidiary / controlled entity'),
    ('relationship_type', 'Corporate structure',            'ASSOCIATE', NULL, 'associate / significant-minority stake'),
    ('relationship_type', 'Corporate structure',            'JV_PARTNER', NULL, 'joint-venture partner'),
    ('relationship_type', 'Corporate structure',            'SPIN_OFF', NULL, 'spun off from the reference security'),
    ('relationship_type', 'Corporate structure',            'MERGER_TARGET', NULL, 'target in a pending / completed merger'),
    ('relationship_type', 'Corporate structure',            'ACQUIRER', NULL, 'acquirer in an M&A transaction'),
    ('relationship_type', 'Corporate structure',            'CROSS_HOLDING', NULL, 'reciprocal / cross-shareholding'),
    ('relationship_type', 'Derivatives / structured linkages', 'UNDERLYING', NULL, 'underlying asset for a derivative'),
    ('relationship_type', 'Derivatives / structured linkages', 'HEDGE', NULL, 'designated hedging instrument'),
    ('relationship_type', 'Derivatives / structured linkages', 'ETF_HOLDING', NULL, 'holding inside an ETF / fund basket'),
    ('relationship_type', 'Derivatives / structured linkages', 'CONVERTIBLE_INTO', NULL, 'convertible bond converts into this equity'),
    ('relationship_type', 'Derivatives / structured linkages', 'WARRANT_ON', NULL, 'warrant exercisable into this security'),
    ('relationship_type', 'Debt / credit',                  'DEBT_ISSUER', NULL, 'issued the debt instrument'),
    ('relationship_type', 'Debt / credit',                  'GUARANTOR', NULL, 'guarantor of the debt'),
    ('relationship_type', 'Debt / credit',                  'CO_ISSUER', NULL, 'co-issuer on a syndicated instrument'),
    ('relationship_type', NULL,                             'OTHER', NULL, NULL)
    ON CONFLICT (type, short_value) DO NOTHING;

INSERT INTO fin_markets.enum_const (type, subtype, short_value, long_value, description) VALUES
    ('cycle_phase', NULL, 'START', NULL, 'initial recovery; activity lifts off from the trough bottom'),
    ('cycle_phase', NULL, 'ACCELERATION', NULL, 'momentum builds; output, earnings and prices rise at an increasing rate'),
    ('cycle_phase', NULL, 'PEAK', NULL, 'maximum expansion; growth rate is highest before the cycle turns down'),
    ('cycle_phase', NULL, 'DECELERATION', NULL, 'expansion slows; momentum fades and leading indicators roll over'),
    ('cycle_phase', NULL, 'TROUGH', NULL, 'cycle bottom; contraction ends and conditions stabilise before next expansion')
ON CONFLICT (type, short_value) DO NOTHING;


INSERT INTO fin_markets.enum_const (type, subtype, short_value, long_value, description) VALUES
    ('news_coverage', NULL, 'NONE',          'none',                   'no analyst coverage and no social media or news presence'),
    ('news_coverage', NULL, 'LITTLE',        'small coverage',         '1–2 analysts; occasional mentions in niche forums or small social media accounts'),
    ('news_coverage', NULL, 'MODERATE',      'moderate coverage',      'handful of analysts; discussed in specialist communities and mid-tier social media accounts'),
    ('news_coverage', NULL, 'SIGNIFICANT',   'significant coverage',   'active analyst community; regular news flow; notable discussion on Twitter/X, Reddit, and finance forums'),
    ('news_coverage', NULL, 'BROAD',         'broad coverage',         'multiple institutional analysts; covered by regional media and consistently active on major social platforms'),
    ('news_coverage', NULL, 'EXTENSIVE',     'extensive coverage',     'wide analyst consensus; featured in prestige outlets (WSJ, FT, Bloomberg); sustained social media buzz across platforms'),
    ('news_coverage', NULL, 'COMPREHENSIVE', 'comprehensive coverage', 'maximum coverage; trending across all major social media; daily prestige media coverage; blue-chip / benchmark security')
ON CONFLICT (type, short_value) DO NOTHING;

-- ============================================================
-- is_enum() — validates a TEXT value against fin_markets.enum_const.
-- Used in CHECK constraints on columns that replaced PostgreSQL ENUM types.
-- Declared STABLE so it may be used in table CHECK constraints and is
-- re-evaluated on every INSERT / UPDATE.
-- ============================================================
CREATE OR REPLACE FUNCTION fin_markets.is_enum(p_type TEXT, p_value TEXT)
RETURNS BOOLEAN
LANGUAGE SQL
STABLE
AS $$
    SELECT EXISTS (
        SELECT 1
        FROM   fin_markets.enum_const
        WHERE  type  = p_type
          AND  short_value = p_value
    );
$$;
