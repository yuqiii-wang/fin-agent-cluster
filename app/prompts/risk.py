"""Prompt template for the risk assessor node."""

from langchain_core.prompts import ChatPromptTemplate

risk_assessment_template = ChatPromptTemplate.from_messages(
    [
        ("system", "You are a risk assessment specialist."),
        (
            "human",
            "Security: '{security_ticker}' ({security_name}), Industry: {industry}\n"
            "Peers: {peers}\n"
            "Opposite industry (hedge): {opposite_industry}\n\n"
            "Fundamental Analysis:\n{fundamental_analysis}\n\n"
            "Technical Analysis:\n{technical_analysis}\n\n"
            "News & Sentiment:\n{news_summary}\n\n"
            "Provide a risk assessment including:\n"
            "- Overall risk level (Low/Medium/High)\n"
            "- Key risk factors (company-specific, industry, macro)\n"
            "- Volatility assessment vs peers and benchmark\n"
            "- Correlation risks (peer / sector / macro)\n"
            "- Recommended position sizing. Respond in English.",
        ),
    ]
)

risk_assessment_prompt = risk_assessment_template.with_config(run_name="risk_assessor")
