"""Prompt template for the technical analyzer node."""

from langchain_core.prompts import ChatPromptTemplate

technical_analysis_template = ChatPromptTemplate.from_messages(
    [
        ("system", "You are a technical analysis expert."),
        (
            "human",
            "Security: '{security_ticker}' ({security_name})\n"
            "Market data:\n{market_data}\n\n"
            "User query: '{query}'\n\n"
            "Provide technical analysis including:\n"
            "- Moving averages: SMA 3/5/10/20/50/200, EMA 12/26\n"
            "- MACD line, signal, histogram\n"
            "- RSI (6, 14), Stochastic %K/%D, ADX\n"
            "- Bollinger Bands position (%B)\n"
            "- Volume ratio vs 20d average, OBV trend\n"
            "- Support/resistance levels, Parabolic SAR\n"
            "- 52-week range position\n"
            "- Trend assessment (bullish/bearish/neutral)\n"
            "Keep it concise. Respond in English.",
        ),
    ]
)

technical_analysis_prompt = technical_analysis_template.with_config(
    run_name="technical_analyzer"
)
