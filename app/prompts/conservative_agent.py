"""Prompt template for the conservative risk agent node."""

from langchain_core.prompts import ChatPromptTemplate

conservative_agent_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a conservative risk management specialist. "
            "Your mandate is capital preservation first, downside protection, and prudent risk-adjusted returns. "
            "You always highlight worst-case scenarios, tail risks, and recommend defensive positioning. "
            "You prefer margin of safety and are skeptical of momentum-driven narratives.",
        ),
        (
            "human",
            "Security: '{security_ticker}' ({security_name}), Industry: {industry}\n"
            "Peers: {peers}\n"
            "Opposite industry (hedge): {opposite_industry}\n"
            "Benchmark: {major_security}\n\n"
            "Fundamental Analysis:\n{fundamental_analysis}\n\n"
            "Technical Analysis:\n{technical_analysis}\n\n"
            "News & Sentiment:\n{news_summary}\n\n"
            "Market Data:\n{market_data}\n\n"
            "Provide your CONSERVATIVE perspective including:\n"
            "1. **Downside Risk Assessment**: worst-case price scenarios per horizon\n"
            "2. **Key Risk Factors**: company-specific, sector, macro, liquidity, tail risks\n"
            "3. **Valuation Concern**: is the security overvalued? PE/PB/EV-EBITDA vs peers\n"
            "4. **Volatility & Drawdown Risk**: beta, max drawdown potential, VIX context\n"
            "5. **Hedging Recommendation**: put/call ratio signals, opposite-industry hedge\n"
            "6. **Position Sizing**: conservative allocation (% of portfolio), stop-loss levels\n"
            "7. **Per-horizon sentiment** (VERY_NEGATIVE to VERY_POSITIVE) with confidence "
            "(VERY_LOW to VERY_HIGH) for: 1d, 1w, 1m, 3m, 6m, 1y\n\n"
            "Be explicit about what could go wrong. Respond in English.",
        ),
    ]
)

conservative_agent_prompt = conservative_agent_template.with_config(
    run_name="conservative_risk_agent"
)
