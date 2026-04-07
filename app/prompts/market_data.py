"""Prompt template for the market data collector node."""

from langchain_core.prompts import ChatPromptTemplate

market_data_template = ChatPromptTemplate.from_messages(
    [
        ("system", "You are a financial data assistant."),
        (
            "human",
            "Security: '{security_ticker}' ({security_name}), Industry: {industry}\n"
            "Peers: {peers}\n"
            "Benchmark: {major_security}\n\n"
            "User query: '{query}'\n\n"
            "Provide realistic market data including:\n"
            "- Current price, 52-week high/low, market cap, volume\n"
            "- Recent price changes (1d, 1w, 1m)\n"
            "- Key technical levels (SMA 50/200, RSI, MACD signal)\n"
            "- Comparison vs benchmark and peers\n"
            "Format as a concise data summary. Respond in English.",
        ),
    ]
)

market_data_prompt = market_data_template.with_config(run_name="market_data_collector")

