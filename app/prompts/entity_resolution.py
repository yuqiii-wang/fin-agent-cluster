"""Prompt template for the entity resolution node.

When an entity is not found in the DB, this prompt asks the LLM to
produce a structured entity description suitable for populating
fin_markets.entities and fin_markets.securities.
"""

from langchain_core.prompts import ChatPromptTemplate

entity_resolution_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a financial data specialist. Provide accurate, factual "
            "company/entity profiles suitable for a financial database. "
            "Always respond in valid JSON.",
        ),
        (
            "human",
            "The entity '{security_name}' (ticker: {security_ticker}) was not found in our database.\n"
            "Provide a JSON profile to populate the record:\n\n"
            '{{\n'
            '  "name": "<legal / display name>",\n'
            '  "short_name": "<abbreviated name>",\n'
            '  "entity_type": "<COMPANY, BANK, EXCHANGE, FUND, HEDGE_FUND, ETF, OTHER>",\n'
            '  "region": "<country name>",\n'
            '  "industry": "<GICS sector>",\n'
            '  "website": "<official website URL>",\n'
            '  "description": "<2-3 sentence business description>",\n'
            '  "established_at": "<YYYY-MM-DD or null>",\n'
            '  "security_type": "<EQUITY, ETF, INDEX, CRYPTO, etc.>",\n'
            '  "exchange": "<primary exchange code, e.g. NASDAQ, NYSE>"\n'
            "}}",
        ),
    ]
)

entity_resolution_prompt = entity_resolution_template.with_config(
    run_name="entity_resolution"
)
