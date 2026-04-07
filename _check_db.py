import asyncio, selectors, httpx

async def test():
    client = httpx.AsyncClient(base_url="https://financialmodelingprep.com", timeout=15)
    for path in ["/api/v3/stock_news", "/stable/news"]:
        try:
            r = await client.get(path, params={"tickers": "AAPL", "limit": 3, "apikey": "caSMC4Bzbfk2O7fnlR1pftST6cWLYSFG"})
            print(path, r.status_code, str(r.text)[:300])
        except Exception as e:
            print(path, "ERROR:", e)
    await client.aclose()

asyncio.run(test(), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
