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
    ('oil',     'CL=F',  'Crude Oil (WTI)',       'macro',        'USD', 'global', 4),
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

