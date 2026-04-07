"""Prompt template for the fundamental analyzer node."""

from langchain_core.prompts import ChatPromptTemplate

fundamental_analysis_template = ChatPromptTemplate.from_messages(
    [
        ("system", "You are a fundamental analysis expert."),
        (
            "human",
            "Security: '{security_ticker}' ({security_name}), Industry: {industry}\n"
            "Entity: {entity_description}\n"
            "Market data:\n{market_data}\n\n"
            "User query: '{query}'\n\n"
            "Provide fundamental analysis including:\n"
            "- P/E, P/B, EV/EBITDA vs industry average\n"
            "- Revenue & earnings trends (TTM)\n"
            "- Profit margins, ROE, ROA\n"
            "- Debt-to-equity, current ratio\n"
            "- Dividend yield & payout policy\n"
            "- Analyst consensus & target price\n"
            "- Earnings surprise history\n"
            "Keep concise with bullet points. Respond in English.",
        ),
    ]
)

fundamental_analysis_prompt = fundamental_analysis_template.with_config(
    run_name="fundamental_analyzer"
)
