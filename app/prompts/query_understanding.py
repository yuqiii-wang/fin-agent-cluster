"""Prompt template for the query understanding node.

Parses raw user query into structured financial intent: security ticker,
company name, industry classification, and analysis intent.
"""

from langchain_core.prompts import ChatPromptTemplate

query_understanding_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a financial query parser. Extract structured information from "
            "natural language financial queries. Always respond in valid JSON.",
        ),
        (
            "human",
            "Parse this financial query and return a JSON object:\n\n"
            "Query: '{query}'\n\n"
            "Return exactly this JSON structure (no markdown fences):\n"
            '{{\n'
            '  "security_ticker": "<primary ticker symbol, e.g. AAPL>",\n'
            '  "security_name": "<full company/security name>",\n'
            '  "industry": "<GICS sector from: ENERGY, MATERIALS, INDUSTRIALS, '
            "CONSUMER_DISCRETIONARY, CONSUMER_STAPLES, HEALTH_CARE, FINANCIALS, "
            'INFORMATION_TECHNOLOGY, COMMUNICATION_SERVICES, UTILITIES, REAL_ESTATE>",\n'
            '  "query_intent": "<brief summary of what the user wants to know>",\n'
            '  "security_type": "<EQUITY, ETF, INDEX, CRYPTO, COMMODITY, BOND, FX, OTHER>",\n'
            '  "region": "<country or Global>",\n'
            '  "exchange": "<exchange code if identifiable, else null>"\n'
            "}}",
        ),
    ]
)

query_understanding_prompt = query_understanding_template.with_config(
    run_name="query_understanding"
)
