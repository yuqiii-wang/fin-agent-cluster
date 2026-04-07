"""Prompt template for the news collector node."""

from langchain_core.prompts import ChatPromptTemplate

news_analysis_template = ChatPromptTemplate.from_messages(
    [
        ("system", "You are a financial news analyst."),
        (
            "human",
            "For the security '{security_ticker}' ({security_name}) in '{industry}':\n\n"
            "Peers: {peers}\n"
            "Market data summary:\n{market_data}\n\n"
            "Provide a concise news & sentiment analysis covering:\n"
            "- Recent material news events affecting this security\n"
            "- Industry-wide news sentiment (positive/negative/neutral)\n"
            "- Macro/geopolitical events impacting the sector\n"
            "- Social media / retail investor sentiment signals\n"
            "- News coverage breadth (NARROW, MODERATE, BROAD, VIRAL)\n\n"
            "Use the 7-point sentiment scale: VERY_NEGATIVE, NEGATIVE, "
            "SLIGHTLY_NEGATIVE, NEUTRAL, SLIGHTLY_POSITIVE, POSITIVE, VERY_POSITIVE.\n\n"
            "Format as concise bullet points. Respond in English.",
        ),
    ]
)

news_analysis_prompt = news_analysis_template.with_config(run_name="news_collector")
