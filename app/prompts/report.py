"""Prompt template for the report generator node."""

from langchain_core.prompts import ChatPromptTemplate

report_generator_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a senior financial analyst synthesizing two opposing perspectives — "
            "a conservative risk agent and an aggressive profit seeker — into a balanced, "
            "actionable investment report. You must present both viewpoints fairly, "
            "highlight where they agree and disagree, and derive a consensus recommendation. "
            "Always include the most significant quantitative metrics.",
        ),
        (
            "human",
            "Compile a final investment report:\n\n"
            "Security: '{security_ticker}' ({security_name}), Industry: {industry}\n"
            "Entity: {entity_description}\n"
            "Peers: {peers}\n"
            "Benchmark: {major_security}\n\n"
            "Query: {query}\n\n"
            "=== DATA INPUTS ===\n"
            "Market Data:\n{market_data}\n\n"
            "Fundamental Analysis:\n{fundamental_analysis}\n\n"
            "Technical Analysis:\n{technical_analysis}\n\n"
            "News & Sentiment:\n{news_summary}\n\n"
            "=== AGENT PERSPECTIVES ===\n"
            "Conservative Risk Agent:\n{conservative_assessment}\n\n"
            "Aggressive Profit Seeker:\n{aggressive_assessment}\n\n"
            "Produce a structured report with:\n\n"
            "1. **Executive Summary** — one-paragraph synthesis of both perspectives\n\n"
            "2. **Key Metrics Dashboard** — table of the most significant metrics:\n"
            "   - Price & Volume: current price, 52w range, avg volume, relative volume\n"
            "   - Valuation: PE, PE forward, PB, EV/EBITDA, PEG, PS\n"
            "   - Profitability: EPS TTM, net margin, ROE, ROA\n"
            "   - Risk: beta, debt/equity, current ratio, short ratio\n"
            "   - Technicals: RSI, MACD, Bollinger %B, price vs SMA50/200\n"
            "   - Options: put/call ratio, IV ATM, IV skew, max pain\n"
            "   - Macro: VIX, yield curve (10y-2y), DXY, credit spread\n\n"
            "3. **Conservative View Summary** — key points from the risk agent\n\n"
            "4. **Aggressive View Summary** — key points from the profit seeker\n\n"
            "5. **Consensus & Divergence** — where both agents agree vs disagree\n\n"
            "6. **Per-horizon Outlook** (use 7-point sentiment scale: "
            "VERY_NEGATIVE to VERY_POSITIVE) with confidence (VERY_LOW to VERY_HIGH):\n"
            "   For each horizon, show conservative vs aggressive vs consensus:\n"
            "   - Next day (1d)\n"
            "   - One week (1w)\n"
            "   - One month (1m)\n"
            "   - One quarter (3m)\n"
            "   - Half year (6m)\n"
            "   - One year (1y)\n\n"
            "7. **Recommendation** (Buy/Hold/Sell) with conviction level\n\n"
            "8. **Target Price Range** — conservative floor vs aggressive ceiling\n\n"
            "9. **Action Items** — specific trade execution guidance\n\n"
            "10. **Risk Disclaimer**\n\n"
            "IMPORTANT: In section 6, output the CONSENSUS per-horizon outlook as a "
            "parseable block exactly like this (one line per horizon):\n"
            "```\n"
            "OUTLOOK_1D: sentiment=<SENTIMENT> confidence=<CONFIDENCE>\n"
            "OUTLOOK_1W: sentiment=<SENTIMENT> confidence=<CONFIDENCE>\n"
            "OUTLOOK_1M: sentiment=<SENTIMENT> confidence=<CONFIDENCE>\n"
            "OUTLOOK_3M: sentiment=<SENTIMENT> confidence=<CONFIDENCE>\n"
            "OUTLOOK_6M: sentiment=<SENTIMENT> confidence=<CONFIDENCE>\n"
            "OUTLOOK_1Y: sentiment=<SENTIMENT> confidence=<CONFIDENCE>\n"
            "```\n"
            "Respond in English.",
        ),
    ]
)

report_generator_prompt = report_generator_template.with_config(
    run_name="report_generator"
)
