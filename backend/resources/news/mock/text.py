"""Mock news articles for local / offline development.

Each entry is a dict compatible with
:class:`~backend.resources.news.models.NewsArticle`.
"""

from __future__ import annotations

from datetime import datetime, timezone

MOCK_NEWS: list[dict] = [
    {
        "id": "news-aapl-001",
        "symbol": "AAPL",
        "title": "Apple Reports Record Q1 2026 Earnings on iPhone 17 Demand",
        "source": "Reuters",
        "published_at": datetime(2026, 1, 29, 14, 0, 0, tzinfo=timezone.utc),
        "content": (
            "Apple Inc. (AAPL) posted record first-quarter earnings on Wednesday, "
            "driven by stronger-than-expected demand for its iPhone 17 lineup and "
            "continued growth in its Services segment. Revenue climbed 12% year-on-year "
            "to $124.3 billion, topping Wall Street estimates of $121.6 billion. "
            "Gross margin expanded to 47.4%, reflecting improved component pricing and "
            "a richer mix of high-margin accessories and software subscriptions. "
            "CEO Tim Cook highlighted the company's accelerating AI integration across "
            "all product lines as a key growth lever heading into the second half of 2026."
        ),
        "url": "https://example.com/news/aapl-q1-2026",
    },
    {
        "id": "news-aapl-002",
        "symbol": "AAPL",
        "title": "Apple Faces EU Antitrust Probe Over App Store Payment Policies",
        "source": "Bloomberg",
        "published_at": datetime(2026, 2, 10, 9, 30, 0, tzinfo=timezone.utc),
        "content": (
            "European Union regulators have opened a fresh antitrust investigation into "
            "Apple's App Store payment practices, potentially exposing the company to "
            "fines of up to 10% of global annual revenue. The European Commission said "
            "it was examining whether Apple's new fee structure for third-party app "
            "marketplaces complies with the Digital Markets Act. Apple said it was "
            "cooperating fully with regulators and remained confident its policies "
            "conform with all applicable laws. Analysts estimate a worst-case fine "
            "could reach $40 billion, though most expect a negotiated settlement."
        ),
        "url": "https://example.com/news/aapl-eu-probe",
    },
    {
        "id": "news-msft-001",
        "symbol": "MSFT",
        "title": "Microsoft Azure Revenue Surges 35% on AI Cloud Demand",
        "source": "CNBC",
        "published_at": datetime(2026, 1, 28, 20, 15, 0, tzinfo=timezone.utc),
        "content": (
            "Microsoft (MSFT) reported quarterly Azure cloud revenue growth of 35% "
            "year-over-year, beating consensus expectations of 32%, as enterprises "
            "continue to deploy AI-powered workloads at scale. The company's Copilot "
            "suite now counts over 200 million monthly active users across Office 365 "
            "and Teams, adding a growing recurring-revenue base to its traditional "
            "software licensing business. CFO Amy Hood raised full-year Azure guidance "
            "to 33–36% growth, citing a robust pipeline of multi-year AI contracts. "
            "Shares rose 5.2% in after-hours trading following the announcement."
        ),
        "url": "https://example.com/news/msft-azure-q2",
    },
    {
        "id": "news-tsla-001",
        "symbol": "TSLA",
        "title": "Tesla Cuts Model Y Price in Europe Amid Rising Competition",
        "source": "Financial Times",
        "published_at": datetime(2026, 3, 5, 8, 0, 0, tzinfo=timezone.utc),
        "content": (
            "Tesla Inc. has reduced the base price of its best-selling Model Y by €3,000 "
            "across major European markets in a bid to defend market share against "
            "growing competition from BYD and Volkswagen's updated electric lineup. "
            "The move comes after Tesla reported a 7% decline in European deliveries "
            "during the fourth quarter of 2025. Industry observers warn the cuts will "
            "compress already-thin margins, and some analysts have revised their "
            "full-year earnings estimates downward. Tesla said the price adjustments "
            "reflect ongoing manufacturing efficiencies at its Berlin Gigafactory."
        ),
        "url": "https://example.com/news/tsla-europe-price-cut",
    },
    {
        "id": "news-nvda-001",
        "symbol": "NVDA",
        "title": "NVIDIA Unveils Blackwell Ultra GPU Architecture at GTC 2026",
        "source": "TechCrunch",
        "published_at": datetime(2026, 3, 18, 18, 0, 0, tzinfo=timezone.utc),
        "content": (
            "NVIDIA Corporation unveiled its next-generation Blackwell Ultra GPU "
            "architecture at its annual GTC developer conference, promising up to "
            "4x the inference throughput of the current Blackwell generation for "
            "large language model workloads. CEO Jensen Huang also announced the "
            "NVLink Fusion interconnect fabric, enabling clusters of up to 576 "
            "GPUs to operate as a single unified compute unit with a shared memory "
            "pool of 1.4 petabytes. Cloud providers AWS, Azure, and Google Cloud "
            "confirmed same-day availability commitments. NVDA shares climbed 8% "
            "on the day to a fresh all-time high."
        ),
        "url": "https://example.com/news/nvda-blackwell-ultra",
    },
    # ── E2E test symbol ─────────────────────────────────────────────────────
    {
        "id": "news-test-001",
        "symbol": "TEST",
        "title": "TEST Corp Beats Q1 2026 Estimates on Strong Product Sales",
        "source": "MockWire",
        "published_at": datetime(2026, 4, 15, 13, 0, 0, tzinfo=timezone.utc),
        "content": (
            "TEST Corp (TEST) reported first-quarter 2026 earnings that beat analyst "
            "estimates by 12%, driven by robust product demand across all segments. "
            "Revenue grew 18% year-on-year to $4.2 billion, while operating margins "
            "expanded to 22%. Management raised full-year guidance citing strong "
            "order backlog and easing supply-chain pressures."
        ),
        "url": "https://example.com/news/test-q1-2026",
    },
    {
        "id": "news-test-002",
        "symbol": "TEST",
        "title": "TEST Corp Announces Strategic Expansion into Asia-Pacific",
        "source": "MockWire",
        "published_at": datetime(2026, 4, 22, 9, 30, 0, tzinfo=timezone.utc),
        "content": (
            "TEST Corp unveiled a $500 million capital allocation plan to expand "
            "its Asia-Pacific distribution network, targeting a 30% increase in "
            "regional revenue over the next two years. The company signed a joint "
            "venture agreement with TechHold Asia Ltd to co-develop localised "
            "product variants. Analysts reacted positively, with three major banks "
            "upgrading the stock to Buy with a median 12-month price target of $85."
        ),
        "url": "https://example.com/news/test-apac-expansion",
    },
    {
        "id": "news-test-003",
        "symbol": "TEST",
        "title": "TEST Corp Increases Buyback Programme to $1 Billion",
        "source": "MockWire",
        "published_at": datetime(2026, 4, 28, 15, 0, 0, tzinfo=timezone.utc),
        "content": (
            "TEST Corp's board authorised an expanded share-repurchase programme "
            "of $1 billion over the next 18 months, doubling the previous $500 "
            "million authorisation. The company also declared a quarterly dividend "
            "of $0.35 per share, representing a 17% increase year-on-year. "
            "The announcements were accompanied by an investor-day presentation "
            "highlighting a three-year roadmap targeting 15% compound annual "
            "revenue growth and 25% operating margins."
        ),
        "url": "https://example.com/news/test-buyback",
    },
]
