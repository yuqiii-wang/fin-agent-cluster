"""Prompt template for the peer discovery node.

Discovers major peers, oligopoly members, opposite-industry hedges,
and benchmark/major security codes for a given security.
"""

from langchain_core.prompts import ChatPromptTemplate

peer_discovery_template = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You are a financial markets expert specializing in industry structure, "
            "competitive landscapes, and cross-sector relationships. "
            "Always respond in valid JSON.",
        ),
        (
            "human",
            "For the security '{security_ticker}' ({security_name}) in the "
            "'{industry}' sector:\n\n"
            "Identify:\n"
            "1. Direct PEER competitors (3-5 tickers)\n"
            "2. OLIGOPOLY_MEMBER — if this industry is dominated by a few players, "
            "list them (e.g. big-4 banks, FAANG, etc.)\n"
            "3. SUPPLIER — major upstream suppliers (1-3 tickers)\n"
            "4. CUSTOMER — major downstream customers (1-3 tickers)\n"
            "5. Opposite/hedge industry — the counter-cyclical industry sector that "
            "tends to move inversely (e.g. UTILITIES vs INFORMATION_TECHNOLOGY)\n"
            "6. Major security — the primary benchmark index for this security "
            "(e.g. SPY for US large-cap equities)\n\n"
            "Return exactly this JSON structure:\n"
            '{{\n'
            '  "peers": ["TICKER1", "TICKER2", "TICKER3"],\n'
            '  "oligopoly_members": ["TICKER1", "TICKER2"],\n'
            '  "suppliers": ["TICKER1"],\n'
            '  "customers": ["TICKER1"],\n'
            '  "opposite_industry": "<GICS sector name>",\n'
            '  "major_security": "<benchmark ticker, e.g. SPY>"\n'
            "}}",
        ),
    ]
)

peer_discovery_prompt = peer_discovery_template.with_config(
    run_name="peer_discovery"
)
