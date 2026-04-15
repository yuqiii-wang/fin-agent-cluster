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
-- news_sectors: GICS sectors + macro — FK target for news_stats.sector
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_markets.news_sectors (
    code        TEXT    PRIMARY KEY,
    label       TEXT    NOT NULL,
    description TEXT,
    sort_order  INTEGER NOT NULL DEFAULT 0
);

INSERT INTO fin_markets.news_sectors (code, label, description, sort_order)
VALUES
    ('technology',             'Technology',             'Technology sector',                    1),
    ('healthcare',             'Healthcare',             'Healthcare & pharmaceuticals',          2),
    ('financials',             'Financials',             'Banks, insurers & financial services',  3),
    ('consumer_discretionary', 'Consumer Discretionary', 'Non-essential consumer goods',          4),
    ('consumer_staples',       'Consumer Staples',       'Essential consumer goods',              5),
    ('energy',                 'Energy',                 'Oil, gas & renewables',                 6),
    ('materials',              'Materials',              'Chemicals, metals & mining',             7),
    ('industrials',            'Industrials',            'Industrial conglomerates & machinery',  8),
    ('utilities',              'Utilities',              'Electric, gas & water utilities',       9),
    ('real_estate',            'Real Estate',            'REITs & real estate companies',        10),
    ('communication_services', 'Communication Services', 'Telecom, media & internet',            11),
    ('macro',                  'Macro',                  'Cross-sector / macroeconomic',         12)
ON CONFLICT (code) DO UPDATE SET
    label       = EXCLUDED.label,
    description = EXCLUDED.description,
    sort_order  = EXCLUDED.sort_order;

-- ---------------------------------------------------------------------------
-- news_topic_level1: top-level news domain taxonomy
--   FK target for news_stats.topic_level1
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_markets.news_topic_level1 (
    code TEXT PRIMARY KEY
);

INSERT INTO fin_markets.news_topic_level1 (code) VALUES
    ('Corporate'),
    ('Macro'),
    ('Geopolitical'),
    ('Market Structure'),
    ('Sector & Industry'),
    ('Other')
ON CONFLICT (code) DO NOTHING;

-- ---------------------------------------------------------------------------
-- news_topic_level2: second-level news category taxonomy
--   FK target for news_stats.topic_level2
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_markets.news_topic_level2 (
    code TEXT PRIMARY KEY
);

INSERT INTO fin_markets.news_topic_level2 (code) VALUES
    ('Financial Performance'),
    ('Corporate Strategy'),
    ('Operations'),
    ('Legal & Regulatory'),
    ('Leadership & Governance'),
    ('Monetary Policy'),
    ('Fiscal Policy'),
    ('Economic Data'),
    ('Commodities & Energy'),
    ('Conflict & Military'),
    ('Trade Policy'),
    ('Political Events'),
    ('Diplomacy'),
    ('Equity Actions'),
    ('Market Events'),
    ('Index Changes'),
    ('Consumer Trends'),
    ('Tech & Innovation'),
    ('Sector Regulation'),
    ('Supply Chain'),
    ('Other')
ON CONFLICT (code) DO NOTHING;

-- Drop legacy generic statics table if it exists
DROP TABLE IF EXISTS fin_markets.statics;

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
-- regions: major stock-market economies
--   code          → ISO-3166-1 alpha-2 country code (or region alias)
--   name          → full country / region name
--   zone          → top-level grouping: global | amer | emea | apac
--   timezone      → standard timezone abbreviation
--   utc_offset    → UTC offset string (std / dst where applicable)
--   currency_code → FK to fin_markets.currencies(code)
--   indexes       → ordered benchmark index tickers for the region;
--                   first element is the primary benchmark index
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_markets.regions (
    code            TEXT    PRIMARY KEY,
    name            TEXT    NOT NULL,
    zone            TEXT    NOT NULL CHECK (zone IN ('global','amer','emea','apac')),
    timezone        TEXT,
    utc_offset      TEXT,
    currency_code   TEXT    REFERENCES fin_markets.currencies(code),
    indexes         TEXT[]
);

-- Seed data (idempotent) — ON CONFLICT updates all mutable columns
INSERT INTO fin_markets.regions
    (code, name, zone, timezone, utc_offset, currency_code, indexes)
VALUES
-- ── Americas ────────────────────────────────────────────────────────────────
('us', 'United States', 'amer', 'ET',   'UTC-5/-4',   'USD',
 ARRAY['NASDAQ_100','NASDAQ','S&P_500','DOW_JONES','RUSSELL']),
('ca', 'Canada',  'amer', 'ET',   'UTC-5/-4',   'CAD',
 ARRAY['S&P/TSX']),
('br', 'Brazil',  'amer', 'BRT',  'UTC-3',      'BRL',
 ARRAY['IBOVESPA','BVSP']),
('mx', 'Mexico',  'amer', 'CT',   'UTC-6/-5',   'MXN',
 ARRAY['IPC']),
-- ── EMEA ────────────────────────────────────────────────────────────────────
('gb', 'United Kingdom', 'emea', 'GMT/BST', 'UTC+0/+1',  'GBP',
 ARRAY['FTSE']),
('de', 'Germany',        'emea', 'CET',     'UTC+1/+2',  'EUR',
 ARRAY['DAX']),
('fr', 'France',         'emea', 'CET',     'UTC+1/+2',  'EUR',
 ARRAY['CAC']),
('ch', 'Switzerland',    'emea', 'CET',     'UTC+1/+2',  'CHF',
 ARRAY['SMI']),
('nl', 'Netherlands',    'emea', 'CET',     'UTC+1/+2',  'EUR',
 ARRAY['AEX']),
('se', 'Sweden',         'emea', 'CET',     'UTC+1/+2',  'SEK',
 ARRAY['OMX']),
('no', 'Norway',         'emea', 'CET',     'UTC+1/+2',  'NOK',
 ARRAY['OBX']),
('dk', 'Denmark',        'emea', 'CET',     'UTC+1/+2',  'DKK',
 NULL),
('it', 'Italy',          'emea', 'CET',     'UTC+1/+2',  'EUR',
 ARRAY['FTSE_MIB','MIB']),
('es', 'Spain',          'emea', 'CET',     'UTC+1/+2',  'EUR',
 ARRAY['IBEX']),
('sa', 'Saudi Arabia',   'emea', 'AST',     'UTC+3',     'SAR',
 ARRAY['TADAWUL','TASI']),
('ae', 'UAE',            'emea', 'GST',     'UTC+4',     'AED',
 NULL),
('qa', 'Qatar',          'emea', 'AST',     'UTC+3',     'QAR',
 NULL),
('il', 'Israel',         'emea', 'IST',     'UTC+2/+3',  'ILS',
 NULL),
('za', 'South Africa',   'emea', 'SAST',    'UTC+2',     'ZAR',
 NULL),
-- ── Asia-Pacific ────────────────────────────────────────────────────────────
('jp', 'Japan',       'apac', 'JST',  'UTC+9',      'JPY',
 ARRAY['NIKKEI','TOPIX']),
('cn', 'China',       'apac', 'CST',  'UTC+8',      'CNY',
 ARRAY['SHANGHAI','CSI_300','SSE','000001','SHENZHEN','399001']),
('hk', 'Hong Kong',   'apac', 'HKT',  'UTC+8',      'HKD',
 ARRAY['HANG_SENG']),
('tw', 'Taiwan',      'apac', 'CST',  'UTC+8',      'TWD',
 ARRAY['TAIEX']),
('kr', 'South Korea', 'apac', 'KST',  'UTC+9',      'KRW',
 ARRAY['KOSPI']),
('sg', 'Singapore',   'apac', 'SGT',  'UTC+8',      'SGD',
 ARRAY['STRAITS','STI']),
('in', 'India',       'apac', 'IST',  'UTC+5:30',   'INR',
 ARRAY['SENSEX','NIFTY','BSE']),
('au', 'Australia',   'apac', 'AEST', 'UTC+10/+11', 'AUD',
 ARRAY['ASX_200','ASX']),
('nz', 'New Zealand', 'apac', 'NZST', 'UTC+12/+13', 'NZD',
 ARRAY['NZX']),
('id', 'Indonesia',   'apac', 'WIB',  'UTC+7',      'IDR',
 ARRAY['IDX']),
('my', 'Malaysia',    'apac', 'MYT',  'UTC+8',      'MYR',
 ARRAY['BURSA','KLCI']),
('th', 'Thailand',    'apac', 'THA',  'UTC+7',      'THB',
 ARRAY['SET']),
('ph', 'Philippines', 'apac', 'PHT',  'UTC+8',      'PHP',
 NULL),
('vn', 'Vietnam',     'apac', 'ICT',  'UTC+7',      'VND',
 NULL)
ON CONFLICT (code) DO UPDATE SET
    name          = EXCLUDED.name,
    zone          = EXCLUDED.zone,
    timezone      = EXCLUDED.timezone,
    utc_offset    = EXCLUDED.utc_offset,
    currency_code = EXCLUDED.currency_code,
    indexes       = EXCLUDED.indexes;

-- ---------------------------------------------------------------------------
-- news_impact_categories: flat matrix of impact classification
--   level1_topic  → domain        (e.g. 'Corporate')
--   level2_topic  → category      (e.g. 'Financial Performance')
--   level3_topic  → specific event (e.g. 'Earnings Beat')  ← stored in news_stats
--   code          → snake_case key for news_stats.impact_category FK
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS fin_markets.news_impact_categories (
    code            TEXT PRIMARY KEY,
    level1_topic    TEXT NOT NULL,
    level2_topic    TEXT NOT NULL,
    level3_topic    TEXT NOT NULL,
    description     TEXT
);

-- Seed data (idempotent)
-- columns: code, level1_topic, level2_topic, level3_topic, description
INSERT INTO fin_markets.news_impact_categories
    (code, level1_topic, level2_topic, level3_topic, description)
VALUES
('earnings_beat',           'Corporate', 'Financial Performance', 'Earnings Beat',                 'EPS above consensus estimate'),
('earnings_miss',           'Corporate', 'Financial Performance', 'Earnings Miss',                 'EPS below consensus estimate'),
('earnings_in_line',        'Corporate', 'Financial Performance', 'Earnings In-Line',              'EPS meets consensus estimate'),
('revenue_beat',            'Corporate', 'Financial Performance', 'Revenue Beat',                  'Revenue above consensus estimate'),
('revenue_miss',            'Corporate', 'Financial Performance', 'Revenue Miss',                  'Revenue below consensus estimate'),
('guidance_raised',         'Corporate', 'Financial Performance', 'Guidance Raised',               'Forward guidance upgraded'),
('guidance_lowered',        'Corporate', 'Financial Performance', 'Guidance Lowered',              'Forward guidance downgraded'),
('guidance_withdrawn',      'Corporate', 'Financial Performance', 'Guidance Withdrawn',            'Forward guidance pulled'),
('merger_acquisition',      'Corporate', 'Corporate Strategy',    'Merger / Acquisition',          'M&A announcement'),
('acquisition_completed',   'Corporate', 'Corporate Strategy',    'Acquisition Completed',         'M&A deal closed'),
('divestiture',             'Corporate', 'Corporate Strategy',    'Divestiture / Spin-off',        'Asset sale or spin-off'),
('strategic_partnership',   'Corporate', 'Corporate Strategy',    'Strategic Partnership',         'Joint venture or alliance'),
('buyback_announced',       'Corporate', 'Corporate Strategy',    'Share Buyback Announced',       'New share repurchase program'),
('product_launch',          'Corporate', 'Operations',            'Product Launch',                'New product or service launch'),
('product_recall',          'Corporate', 'Operations',            'Product Recall',                'Safety recall or defect notice'),
('operational_disruption',  'Corporate', 'Operations',            'Operational Disruption',        'Factory shutdown, cyberattack, or outage'),
('sec_investigation',       'Corporate', 'Legal & Regulatory',   'SEC / Regulatory Investigation','Probe by securities or antitrust regulator'),
('lawsuit_filed',           'Corporate', 'Legal & Regulatory',   'Lawsuit Filed',                 'Material lawsuit initiated'),
('lawsuit_settled',         'Corporate', 'Legal & Regulatory',   'Lawsuit Settled',               'Material lawsuit settled'),
('fda_approval',            'Corporate', 'Legal & Regulatory',   'FDA Approval',                  'Drug or device approved by FDA'),
('fda_rejection',           'Corporate', 'Legal & Regulatory',   'FDA Rejection',                 'Drug or device rejected by FDA'),
('antitrust_action',        'Corporate', 'Legal & Regulatory',   'Antitrust Action',              'Antitrust investigation or ruling'),
('ceo_change',              'Corporate', 'Leadership & Governance', 'CEO Change',                 'CEO appointed or departed'),
('cfo_change',              'Corporate', 'Leadership & Governance', 'CFO Change',                 'CFO appointed or departed'),
('board_change',            'Corporate', 'Leadership & Governance', 'Board Change',               'Material board composition change'),
('insider_buy',             'Corporate', 'Leadership & Governance', 'Insider Purchase',           'Executive or director buys shares'),
('insider_sell',            'Corporate', 'Leadership & Governance', 'Insider Sale',               'Executive or director sells shares'),
('analyst_upgrade',         'Corporate', 'Leadership & Governance', 'Analyst Upgrade',            'Analyst raises rating or price target'),
('analyst_downgrade',       'Corporate', 'Leadership & Governance', 'Analyst Downgrade',          'Analyst lowers rating or price target'),
('dividend_increase',       'Corporate', 'Leadership & Governance', 'Dividend Increase',          'Dividend per share raised'),
('dividend_cut',            'Corporate', 'Leadership & Governance', 'Dividend Cut / Suspension',  'Dividend reduced or suspended'),
('rate_hike',               'Macro', 'Monetary Policy', 'Rate Hike',                   'Central bank raises benchmark rate'),
('rate_cut',                'Macro', 'Monetary Policy', 'Rate Cut',                    'Central bank cuts benchmark rate'),
('rate_hold',               'Macro', 'Monetary Policy', 'Rate Hold',                   'Central bank holds rate unchanged'),
('qe_announced',            'Macro', 'Monetary Policy', 'QE Announced',                'Quantitative easing program announced'),
('qt_announced',            'Macro', 'Monetary Policy', 'QT Announced',                'Quantitative tightening announced'),
('guidance_hawkish',        'Macro', 'Monetary Policy', 'Hawkish Forward Guidance',    'Central bank signals tighter policy ahead'),
('guidance_dovish',         'Macro', 'Monetary Policy', 'Dovish Forward Guidance',     'Central bank signals looser policy ahead'),
('bank_stress',             'Macro', 'Monetary Policy', 'Banking System Stress',       'Bank failure or systemic credit stress'),
('stimulus_package',        'Macro', 'Fiscal Policy', 'Stimulus Package',              'Government fiscal stimulus announced'),
('tax_reform',              'Macro', 'Fiscal Policy', 'Tax Reform',                    'Major change in tax policy'),
('govt_shutdown',           'Macro', 'Fiscal Policy', 'Government Shutdown',           'Government shutdown or default risk'),
('debt_ceiling',            'Macro', 'Fiscal Policy', 'Debt Ceiling',                  'Debt ceiling standoff or resolution'),
('infrastructure_bill',     'Macro', 'Fiscal Policy', 'Infrastructure / Spending Bill','Major government spending legislation'),
('cpi_release',             'Macro', 'Economic Data', 'CPI Release',                   'Consumer Price Index print'),
('pce_release',             'Macro', 'Economic Data', 'PCE Release',                   'Personal Consumption Expenditures print'),
('gdp_release',             'Macro', 'Economic Data', 'GDP Release',                   'Gross Domestic Product report'),
('nonfarm_payrolls',        'Macro', 'Economic Data', 'Nonfarm Payrolls',              'US monthly jobs report'),
('unemployment_rate',       'Macro', 'Economic Data', 'Unemployment Rate',             'Unemployment rate release'),
('jobless_claims',          'Macro', 'Economic Data', 'Jobless Claims',                'Weekly initial or continuing claims'),
('retail_sales',            'Macro', 'Economic Data', 'Retail Sales',                  'Monthly retail sales data'),
('pmi_release',             'Macro', 'Economic Data', 'PMI Release',                   'Manufacturing or services PMI print'),
('consumer_confidence',     'Macro', 'Economic Data', 'Consumer Confidence',           'Consumer confidence / sentiment index'),
('housing_data',            'Macro', 'Economic Data', 'Housing Data',                  'Housing starts, permits, or existing sales'),
('trade_balance',           'Macro', 'Economic Data', 'Trade Balance',                 'Import/export balance report'),
('oil_price_move',          'Macro', 'Commodities & Energy', 'Oil Price Move',          'Significant crude oil price change'),
('nat_gas_price_move',      'Macro', 'Commodities & Energy', 'Natural Gas Price Move',  'Significant natural gas price change'),
('gold_price_move',         'Macro', 'Commodities & Energy', 'Gold Price Move',         'Significant gold price change'),
('opec_decision',           'Macro', 'Commodities & Energy', 'OPEC Decision',           'OPEC+ supply or production decision'),
('commodity_supply_shock',  'Macro', 'Commodities & Energy', 'Commodity Supply Shock',  'Unexpected supply disruption'),
('war_outbreak',            'Geopolitical', 'Conflict & Military', 'War / Conflict Outbreak',   'Outbreak of armed conflict'),
('ceasefire',               'Geopolitical', 'Conflict & Military', 'Ceasefire / Peace Deal',    'Ceasefire or peace agreement'),
('military_escalation',     'Geopolitical', 'Conflict & Military', 'Military Escalation',       'Intensification of existing conflict'),
('terrorism_event',         'Geopolitical', 'Conflict & Military', 'Terrorism / Civil Unrest',  'Major terrorism or civil unrest'),
('tariff_imposed',          'Geopolitical', 'Trade Policy', 'Tariff Imposed',            'New tariff or trade barrier announced'),
('tariff_removed',          'Geopolitical', 'Trade Policy', 'Tariff Removed',            'Existing tariff lifted or reduced'),
('trade_deal',              'Geopolitical', 'Trade Policy', 'Trade Deal Signed',         'Bilateral or multilateral trade agreement'),
('trade_war_escalation',    'Geopolitical', 'Trade Policy', 'Trade War Escalation',      'Retaliatory tariffs or trade war intensifies'),
('sanctions_imposed',       'Geopolitical', 'Trade Policy', 'Sanctions Imposed',         'Economic sanctions announced'),
('sanctions_lifted',        'Geopolitical', 'Trade Policy', 'Sanctions Lifted',          'Economic sanctions removed'),
('export_control',          'Geopolitical', 'Trade Policy', 'Export Controls',           'Technology or goods export restrictions'),
('election_result',         'Geopolitical', 'Political Events', 'Election Result',        'Major election outcome'),
('political_instability',   'Geopolitical', 'Political Events', 'Political Instability',  'Political crisis or uncertainty'),
('regime_change',           'Geopolitical', 'Political Events', 'Regime Change',          'Change of government or leadership'),
('impeachment_event',       'Geopolitical', 'Political Events', 'Impeachment / Removal',  'Leadership removal or impeachment'),
('summit_meeting',          'Geopolitical', 'Diplomacy', 'Diplomatic Summit',             'High-level bilateral or multilateral meeting'),
('treaty_signed',           'Geopolitical', 'Diplomacy', 'Treaty / Agreement Signed',    'International agreement finalized'),
('diplomatic_breakdown',    'Geopolitical', 'Diplomacy', 'Diplomatic Breakdown',         'Relations severed or ambassador expelled'),
('stock_split',             'Market Structure', 'Equity Actions', 'Stock Split',           'Forward stock split announced'),
('reverse_split',           'Market Structure', 'Equity Actions', 'Reverse Stock Split',   'Reverse split announced'),
('ipo',                     'Market Structure', 'Equity Actions', 'IPO',                   'Initial public offering'),
('secondary_offering',      'Market Structure', 'Equity Actions', 'Secondary Offering',    'Additional share issuance'),
('delisting',               'Market Structure', 'Equity Actions', 'Delisting',             'Stock delisted from exchange'),
('short_squeeze',           'Market Structure', 'Market Events', 'Short Squeeze',          'Rapid short cover-driven price spike'),
('circuit_breaker',         'Market Structure', 'Market Events', 'Circuit Breaker',        'Exchange halts trading on extreme move'),
('margin_call_wave',        'Market Structure', 'Market Events', 'Margin Call Wave',       'Systemic forced selling from margin calls'),
('liquidity_crisis',        'Market Structure', 'Market Events', 'Liquidity Crisis',       'Market-wide liquidity dislocation'),
('flash_crash',             'Market Structure', 'Market Events', 'Flash Crash',            'Sudden extreme intraday price drop'),
('index_addition',          'Market Structure', 'Index Changes', 'Index Addition',         'Stock added to major benchmark index'),
('index_removal',           'Market Structure', 'Index Changes', 'Index Removal',          'Stock removed from major benchmark index'),
('index_rebalancing',       'Market Structure', 'Index Changes', 'Index Rebalancing',      'Periodic index weight rebalancing'),
('consumer_event',          'Sector & Industry', 'Consumer Trends', 'Consumer Event',           'Black Friday, holiday season, major sale'),
('consumer_spending_data',  'Sector & Industry', 'Consumer Trends', 'Consumer Spending Data',   'Official consumer spending report'),
('brand_controversy',       'Sector & Industry', 'Consumer Trends', 'Brand / ESG Controversy',  'Boycott, PR crisis, ESG scandal'),
('credit_card_data',        'Sector & Industry', 'Consumer Trends', 'Credit Card Data',         'High-frequency consumer spending signal'),
('ai_breakthrough',         'Sector & Industry', 'Tech & Innovation', 'AI / ML Breakthrough',       'Significant AI or ML development'),
('patent_granted',          'Sector & Industry', 'Tech & Innovation', 'Patent Granted',             'Material patent awarded'),
('patent_lawsuit',          'Sector & Industry', 'Tech & Innovation', 'Patent Litigation',          'Patent infringement suit'),
('tech_standard_change',    'Sector & Industry', 'Tech & Innovation', 'Technology Standard Change', 'New protocol, standard, or platform shift'),
('sector_policy_change',    'Sector & Industry', 'Sector Regulation', 'Sector Policy Change',  'New industry-wide regulation or rule'),
('carbon_regulation',       'Sector & Industry', 'Sector Regulation', 'Carbon / Environmental Rule', 'Climate or emissions regulation'),
('healthcare_policy',       'Sector & Industry', 'Sector Regulation', 'Healthcare Policy',     'Drug pricing, insurance, or ACA change'),
('banking_regulation',      'Sector & Industry', 'Sector Regulation', 'Banking Regulation',    'Capital requirements, Basel rules, etc.'),
('supply_chain_disruption', 'Sector & Industry', 'Supply Chain', 'Supply Chain Disruption',   'Port congestion, logistics failure'),
('component_shortage',      'Sector & Industry', 'Supply Chain', 'Component / Material Shortage', 'Chip, commodity, or input shortage'),
('factory_outage',          'Sector & Industry', 'Supply Chain', 'Factory / Plant Outage',    'Unplanned production halt'),
('supply_chain_restored',   'Sector & Industry', 'Supply Chain', 'Supply Chain Restored',     'Supply chain disruption resolved; flow normalised'),
('shortage_resolved',       'Sector & Industry', 'Supply Chain', 'Shortage Resolved',         'Component or material shortage cleared'),
('factory_resumed',         'Sector & Industry', 'Supply Chain', 'Factory / Plant Resumed',   'Unplanned production halt ended; output restored'),
('deal_terminated',         'Corporate', 'Corporate Strategy',    'Deal / M&A Terminated',         'Announced M&A or partnership deal falls through'),
('partnership_dissolved',   'Corporate', 'Corporate Strategy',    'Partnership Dissolved',         'Strategic partnership or joint venture ended'),
('buyback_suspended',       'Corporate', 'Corporate Strategy',    'Share Buyback Suspended',       'Active repurchase program paused or cancelled'),
('product_discontinued',    'Corporate', 'Operations',            'Product Discontinued',          'Existing product or service withdrawn from market'),
('recall_lifted',           'Corporate', 'Operations',            'Recall Lifted',                 'Product recall resolved and safety clearance given'),
('operations_restored',     'Corporate', 'Operations',            'Operations Restored',           'Normal operations resumed after disruption'),
('investigation_closed',    'Corporate', 'Legal & Regulatory',   'Investigation Closed / Cleared','Regulatory or SEC probe closed without action'),
('antitrust_cleared',       'Corporate', 'Legal & Regulatory',   'Antitrust Cleared',             'Antitrust case dismissed or deal unconditionally approved'),
('bank_stress_resolved',    'Macro', 'Monetary Policy', 'Banking Stress Resolved',     'Banking crisis stabilised; systemic risk subsides'),
('austerity_measures',      'Macro', 'Fiscal Policy', 'Austerity Measures',            'Government spending cuts or fiscal tightening'),
('govt_shutdown_ended',     'Macro', 'Fiscal Policy', 'Government Shutdown Ended',     'Shutdown resolved; government funding restored'),
('debt_ceiling_resolved',   'Macro', 'Fiscal Policy', 'Debt Ceiling Resolved',         'Debt ceiling standoff resolved; default averted'),
('spending_cut',            'Macro', 'Fiscal Policy', 'Government Spending Cut',       'Major reduction in government expenditure announced'),
-- GDP
('gdp_above_expected',      'Macro', 'Economic Data', 'GDP Above Expected',            'GDP growth beats consensus estimate; expansion signal'),
('gdp_below_expected',      'Macro', 'Economic Data', 'GDP Below Expected',            'GDP growth misses consensus; contraction / recession risk'),
('inflation_above_expected','Macro', 'Economic Data', 'Inflation Above Expected',      'CPI / PCE print higher than forecast; hawkish pressure'),
('inflation_below_expected','Macro', 'Economic Data', 'Inflation Below Expected',      'CPI / PCE print lower than forecast; dovish signal'),
('payrolls_above_expected', 'Macro', 'Economic Data', 'Payrolls Above Expected',       'Nonfarm payrolls beat consensus; labour market strong'),
('payrolls_below_expected', 'Macro', 'Economic Data', 'Payrolls Below Expected',       'Nonfarm payrolls miss consensus; labour market cooling'),
('unemployment_rising',     'Macro', 'Economic Data', 'Unemployment Rising',           'Unemployment rate trending higher; labour market weakening'),
('unemployment_falling',    'Macro', 'Economic Data', 'Unemployment Falling',          'Unemployment rate trending lower; labour market tightening'),
('pmi_expansion',           'Macro', 'Economic Data', 'PMI Expansion',                 'PMI above 50; manufacturing or services sector expanding'),
('pmi_contraction',         'Macro', 'Economic Data', 'PMI Contraction',               'PMI below 50; manufacturing or services sector contracting'),
('consumer_confidence_rise','Macro', 'Economic Data', 'Consumer Confidence Rising',    'Consumer confidence index improves; spending outlook brightens'),
('consumer_confidence_fall','Macro', 'Economic Data', 'Consumer Confidence Falling',   'Consumer confidence index deteriorates; spending outlook dims'),
('housing_market_heating',  'Macro', 'Economic Data', 'Housing Market Heating',        'Rising starts, permits, and prices signal hot housing market'),
('housing_market_cooling',  'Macro', 'Economic Data', 'Housing Market Cooling',        'Falling starts, permits, or prices signal cooling housing'),
('trade_deficit_widening',  'Macro', 'Economic Data', 'Trade Deficit Widening',        'Current account / trade deficit increases'),
('trade_deficit_narrowing', 'Macro', 'Economic Data', 'Trade Deficit Narrowing',       'Current account / trade deficit shrinks'),
('oil_price_surge',         'Macro', 'Commodities & Energy', 'Oil Price Surge',         'Sharp crude oil price increase (supply cut or demand spike)'),
('oil_price_crash',         'Macro', 'Commodities & Energy', 'Oil Price Crash',         'Sharp crude oil price drop (demand collapse or supply glut)'),
('nat_gas_price_surge',     'Macro', 'Commodities & Energy', 'Natural Gas Price Surge', 'Sharp natural gas price increase'),
('nat_gas_price_crash',     'Macro', 'Commodities & Energy', 'Natural Gas Price Crash', 'Sharp natural gas price drop'),
('gold_price_surge',        'Macro', 'Commodities & Energy', 'Gold Price Surge',        'Sharp gold price increase; risk-off or inflation hedge bid'),
('gold_price_crash',        'Macro', 'Commodities & Energy', 'Gold Price Crash',        'Sharp gold price drop; risk-on or dollar strength'),
('commodity_supply_glut',   'Macro', 'Commodities & Energy', 'Commodity Supply Glut',   'Excess commodity supply drives prices lower'),
('military_deescalation',   'Geopolitical', 'Conflict & Military', 'Military De-escalation',    'Reduction in conflict intensity or troop withdrawal'),
('civil_unrest_resolved',   'Geopolitical', 'Conflict & Military', 'Civil Unrest Resolved',     'Protests or civil unrest end; order restored'),
('trade_war_deescalation',  'Geopolitical', 'Trade Policy', 'Trade War De-escalation',   'Trade war intensity reduced; truce, pause, or rollback'),
('export_control_lifted',   'Geopolitical', 'Trade Policy', 'Export Controls Lifted',    'Technology or goods export restrictions removed'),
('political_stabilization', 'Geopolitical', 'Political Events', 'Political Stabilization', 'Political crisis resolved; government stability restored'),
('diplomatic_normalization','Geopolitical', 'Diplomacy', 'Diplomatic Normalization',    'Diplomatic relations restored after breakdown'),
('market_stabilization',    'Market Structure', 'Market Events', 'Market Stabilization',  'Market conditions normalise after dislocation or crash'),
('consumer_spending_rise',  'Sector & Industry', 'Consumer Trends', 'Consumer Spending Rising',  'Consumer spending trend accelerating above expectations'),
('consumer_spending_fall',  'Sector & Industry', 'Consumer Trends', 'Consumer Spending Falling', 'Consumer spending trend decelerating below expectations'),
('brand_rehabilitation',    'Sector & Industry', 'Consumer Trends', 'Brand Rehabilitation',      'Brand reputation recovering after controversy'),
('other',                   'Other', 'Other', 'Other',                                         'Unclassified event type')

ON CONFLICT (code) DO NOTHING;



