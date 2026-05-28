# Peer Company Identification Skill

## What makes a company a valid peer?

A peer (or comparable company) for a target stock must satisfy **all** of the following criteria:

1. **Same industry / sector** — operates in the same primary industry vertical (e.g. both are semiconductor designers, both are cloud hyperscalers, both are commercial banks).
2. **Similar business model** — revenue is generated through substantially the same mechanism (e.g. both sell SaaS subscriptions, both run ad-funded platforms, both are exchange-traded asset managers).
3. **Publicly listed equity** — has a tradeable primary-exchange ticker symbol (NYSE, NASDAQ, LSE, TSE, etc.).
4. **Comparable market segment** — serves an overlapping customer base or competes in the same product category (e.g. EV manufacturers competing for the same buyer demographics).
5. **Explicitly cited on the page** — the company's name (or ticker/symbol) must appear on the crawled page as a peer, competitor, or comparable. Do NOT invent companies not present in the text.

Do NOT include:
- Index names, ETFs, or funds (e.g. SPY, QQQ, XLK)
- The target company itself
- Acronyms or uppercase tokens that are not company names (e.g. SEC, NYSE, P, E, B, SMS)
- Companies in unrelated industries even if mentioned on the page

## JSON output format

The transform script's stdout must be a single JSON object with this exact structure:

```json
{
  "symbols": ["SYMBOL1", "SYMBOL2", "SYMBOL3"],
}
```

- `symbols`: array of primary-exchange ticker symbols (uppercase), one per peer company. Deduplicated. Maximum 10 entries.

## Ticker/symbol extraction rules

- Include ONLY companies you actually observed in the markdown — do not invent entries.
- Detect each company name with a word-boundary case-insensitive regex:

```python
re.search(r'\bsymbol\b', text, re.IGNORECASE)
```

e.g.,

```python
re.search(r'\bAMZN\b', text, re.IGNORECASE)
re.search(r'\bGOOG\b', text, re.IGNORECASE)
```

- Collect tickers for all matched names; deduplicate; output only confirmed tickers.

If in provisioned text explicitly said a company name as the competitors/peers but no symbol provided, it is ok to create the corresponding symbol for it.
It is mandatory to also output this company name if it is by guess of the symbol.

In output, write

```json
{
  "symbols": ["SYMBOL1", "SYMBOL2", "SYMBOL3", "SYMBOL4"],
  "companies" : ["company_full_name_4"]
}
```
