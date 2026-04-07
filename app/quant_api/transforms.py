"""Transforms: API responses → Pydantic domain models.

Provider-specific functions (``fmp_*``, ``yf_*``) convert raw JSON into
fin_markets Pydantic records ready for DB insertion.

``bars_to_trades`` is provider-agnostic because both FMP and yfinance return
OHLCV bars with the same field names (date, open, high, low, close, volume).
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from app.models.markets.securities import SecurityRecord, EntityRecord
from app.models.markets.trades import SecurityTradeRecord
from app.models.markets.news import NewsRecord
from app.models.markets.fundamentals import SecurityExtRecord, SecurityExtAggregRecord
from app.models.markets.macro import MacroEconomicsRecord


def fmp_profile_to_security(profile: dict[str, Any]) -> SecurityRecord:
    """Convert FMP company profile to SecurityRecord.

    Args:
        profile: Raw JSON from /api/v3/profile/{symbol}.

    Returns:
        SecurityRecord ready for insertion into fin_markets.securities.
    """
    sector_map = {
        "Technology": "INFORMATION_TECHNOLOGY",
        "Healthcare": "HEALTH_CARE",
        "Financial Services": "FINANCIALS",
        "Consumer Cyclical": "CONSUMER_DISCRETIONARY",
        "Consumer Defensive": "CONSUMER_STAPLES",
        "Communication Services": "COMMUNICATION_SERVICES",
        "Industrials": "INDUSTRIALS",
        "Energy": "ENERGY",
        "Basic Materials": "MATERIALS",
        "Utilities": "UTILITIES",
        "Real Estate": "REAL_ESTATE",
    }
    return SecurityRecord(
        ticker=profile.get("symbol", ""),
        name=profile.get("companyName", ""),
        security_type="EQUITY" if not profile.get("isEtf") else "ETF",
        exchange=profile.get("exchangeShortName"),
        region=_exchange_to_region(profile.get("exchangeShortName", "")),
        industry=sector_map.get(profile.get("sector", ""), None),
        description=profile.get("description"),
        extra={
            "cik": profile.get("cik"),
            "isin": profile.get("isin"),
            "cusip": profile.get("cusip"),
            "ipo_date": profile.get("ipoDate"),
        },
    )


def fmp_profile_to_entity(profile: dict[str, Any]) -> EntityRecord:
    """Convert FMP company profile to EntityRecord.

    Args:
        profile: Raw JSON from /api/v3/profile/{symbol}.

    Returns:
        EntityRecord ready for insertion into fin_markets.entities.
    """
    return EntityRecord(
        name=profile.get("companyName", ""),
        short_name=profile.get("symbol"),
        entity_type="COMPANY",
        region=_exchange_to_region(profile.get("exchangeShortName", "")),
        website=profile.get("website"),
        description=profile.get("description"),
    )


def fmp_historical_to_trades(
    bars: list[dict[str, Any]], security_id: int, interval: str = "1d"
) -> list[SecurityTradeRecord]:
    """Convert FMP historical price bars to SecurityTradeRecord list.

    Args:
        bars: Raw JSON list from /api/v3/historical-price-full/{symbol}.
        security_id: FK to fin_markets.securities.
        interval: Trade interval code.

    Returns:
        List of SecurityTradeRecord ready for bulk insertion.
    """
    records = []
    for bar in bars:
        trade_date_str = bar.get("date", "")
        trade_date = date.fromisoformat(trade_date_str[:10]) if trade_date_str else None
        if not trade_date:
            continue
        records.append(
            SecurityTradeRecord(
                security_id=security_id,
                trade_date=trade_date,
                interval=interval,
                open=Decimal(str(bar.get("open", 0))),
                high=Decimal(str(bar.get("high", 0))),
                low=Decimal(str(bar.get("low", 0))),
                close=Decimal(str(bar.get("close", 0))),
                volume=bar.get("volume"),
            )
        )
    return records


def fmp_news_to_record(article: dict[str, Any]) -> NewsRecord:
    """Convert FMP news article to NewsRecord.

    Args:
        article: Raw JSON from /api/v3/stock_news.

    Returns:
        NewsRecord ready for insertion into fin_markets.news.
    """
    pub_str = article.get("publishedDate", "")
    published_at = datetime.fromisoformat(pub_str) if pub_str else datetime.now(timezone.utc)

    return NewsRecord(
        external_id=article.get("url"),
        data_source="GENERIC_WEB_SUMMARY",
        source_url=article.get("url"),
        published_at=published_at,
        title=article.get("title", ""),
        body=article.get("text"),
        extra={"site": article.get("site"), "image": article.get("image")},
    )


def fmp_metrics_to_security_ext(
    metrics: dict[str, Any], ratios: dict[str, Any], security_id: int
) -> SecurityExtRecord:
    """Convert FMP key-metrics + ratios to SecurityExtRecord.

    Args:
        metrics: Raw JSON from /api/v3/key-metrics-ttm/{symbol}.
        ratios: Raw JSON from /api/v3/ratios-ttm/{symbol}.
        security_id: FK to fin_markets.securities.

    Returns:
        SecurityExtRecord ready for insertion into fin_markets.security_exts.
    """
    return SecurityExtRecord(
        security_id=security_id,
        published_at=datetime.now(timezone.utc),
        market_cap_usd=_dec(metrics.get("marketCapTTM")),
        pe_ratio=_dec(metrics.get("peRatioTTM")),
        pb_ratio=_dec(metrics.get("pbRatioTTM")),
        net_margin=_dec(ratios.get("netProfitMarginTTM")),
        eps_ttm=_dec(metrics.get("netIncomePerShareTTM")),
        revenue_ttm=_dec(metrics.get("revenuePerShareTTM")),
        debt_to_equity=_dec(metrics.get("debtToEquityTTM")),
        dividend_yield=_dec(metrics.get("dividendYieldTTM")),
    )


def fmp_metrics_to_ext_aggreg(
    metrics: dict[str, Any], ratios: dict[str, Any], security_ext_id: int
) -> SecurityExtAggregRecord:
    """Convert FMP metrics/ratios to SecurityExtAggregRecord.

    Args:
        metrics: Raw JSON from /api/v3/key-metrics-ttm/{symbol}.
        ratios: Raw JSON from /api/v3/ratios-ttm/{symbol}.
        security_ext_id: FK to fin_markets.security_exts.

    Returns:
        SecurityExtAggregRecord ready for insertion.
    """
    return SecurityExtAggregRecord(
        security_ext_id=security_ext_id,
        published_at=datetime.now(timezone.utc),
        pe_forward=_dec(metrics.get("peRatioTTM")),
        ps_ratio=_dec(ratios.get("priceToSalesRatioTTM")),
        ev_ebitda=_dec(metrics.get("enterpriseValueOverEBITDATTM")),
        peg_ratio=_dec(metrics.get("pegRatioTTM")),
        roe=_dec(ratios.get("returnOnEquityTTM")),
        roa=_dec(ratios.get("returnOnAssetsTTM")),
        gross_margin=_dec(ratios.get("grossProfitMarginTTM")),
        operating_margin=_dec(ratios.get("operatingProfitMarginTTM")),
    )


def fmp_economic_to_macro(
    records: list[dict[str, Any]], indicator_name: str, region: str = "United States"
) -> list[MacroEconomicsRecord]:
    """Convert FMP economic indicator data to MacroEconomicsRecord list.

    Args:
        records: Raw JSON list from /api/v4/economic.
        indicator_name: Human-readable indicator name (e.g. 'GDP', 'CPI').
        region: Geographic region (defaults to 'United States').

    Returns:
        List of MacroEconomicsRecord ready for bulk insertion.
    """
    results = []
    for rec in records:
        date_str = rec.get("date", "")
        if not date_str:
            continue
        results.append(
            MacroEconomicsRecord(
                published_at=datetime.fromisoformat(date_str),
                region=region,
                actual=_dec(rec.get("value")),
                indicator_name=indicator_name,
                category="MACRO",
            )
        )
    return results


# ── helpers ──────────────────────────────────────────────────────────────────

def _dec(v: Any) -> Decimal | None:
    """Safely convert a value to Decimal, returning None on failure."""
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _exchange_to_region(exchange: str) -> str | None:
    """Map exchange short name to fin_markets region.

    Args:
        exchange: Exchange short name (e.g. 'NYSE', 'TSE').

    Returns:
        Region string or None if unmapped.
    """
    mapping = {
        "NYSE": "United States",
        "NASDAQ": "United States",
        "AMEX": "United States",
        "TSE": "Japan",
        "LSE": "United Kingdom",
        "HKSE": "Hong Kong",
        "SSE": "China",
        "SZSE": "China",
        "TSX": "Canada",
        "ASX": "Australia",
        "BSE": "India",
        "NSE": "India",
        "XETRA": "Germany",
        "EURONEXT": "France",
        "SGX": "Singapore",
        "KRX": "South Korea",
    }
    return mapping.get(exchange.upper()) if exchange else None


# ── Provider-agnostic ─────────────────────────────────────────────────────────

def bars_to_trades(
    bars: list[dict[str, Any]], security_id: int, interval: str = "1d"
) -> list[SecurityTradeRecord]:
    """Convert OHLCV bar dicts to SecurityTradeRecord list.

    Works for both FMP and yfinance because both providers normalise bars to
    ``{date, open, high, low, close, volume}``.

    Args:
        bars: List of OHLCV dicts with keys: date, open, high, low, close, volume.
        security_id: FK to fin_markets.securities.
        interval: Trade interval code (e.g. '1d').

    Returns:
        List of SecurityTradeRecord ready for bulk insertion.
    """
    return fmp_historical_to_trades(bars, security_id, interval)


# ── yfinance transforms ───────────────────────────────────────────────────────

_SECTOR_MAP: dict[str, str] = {
    "Technology": "INFORMATION_TECHNOLOGY",
    "Healthcare": "HEALTH_CARE",
    "Financial Services": "FINANCIALS",
    "Consumer Cyclical": "CONSUMER_DISCRETIONARY",
    "Consumer Defensive": "CONSUMER_STAPLES",
    "Communication Services": "COMMUNICATION_SERVICES",
    "Industrials": "INDUSTRIALS",
    "Energy": "ENERGY",
    "Basic Materials": "MATERIALS",
    "Utilities": "UTILITIES",
    "Real Estate": "REAL_ESTATE",
}


def yf_profile_to_security(profile: dict[str, Any]) -> SecurityRecord:
    """Convert yfinance company profile dict to SecurityRecord.

    Args:
        profile: Normalised dict returned by ``YFinanceClient.get_company_profile()``.

    Returns:
        SecurityRecord ready for insertion into fin_markets.securities.
    """
    exchange = profile.get("exchange", "")
    return SecurityRecord(
        ticker=profile.get("symbol", ""),
        name=profile.get("companyName", ""),
        security_type="EQUITY",
        exchange=exchange,
        region=_exchange_to_region(exchange),
        industry=_SECTOR_MAP.get(profile.get("sector", ""), None),
        description=profile.get("description"),
        extra={
            "country": profile.get("country"),
            "employees": profile.get("employees"),
            "website": profile.get("website"),
        },
    )


def yf_profile_to_entity(profile: dict[str, Any]) -> EntityRecord:
    """Convert yfinance company profile dict to EntityRecord.

    Args:
        profile: Normalised dict returned by ``YFinanceClient.get_company_profile()``.

    Returns:
        EntityRecord ready for insertion into fin_markets.entities.
    """
    exchange = profile.get("exchange", "")
    return EntityRecord(
        name=profile.get("companyName", ""),
        short_name=profile.get("symbol"),
        entity_type="COMPANY",
        region=_exchange_to_region(exchange),
        website=profile.get("website"),
        description=profile.get("description"),
    )


def yf_news_to_record(article: dict[str, Any]) -> NewsRecord:
    """Convert yfinance news article dict to NewsRecord.

    Args:
        article: Normalised dict returned by ``YFinanceClient.get_stock_news()``.

    Returns:
        NewsRecord ready for insertion into fin_markets.news.
    """
    pub_str = article.get("publishedDate", "")
    published_at = datetime.fromisoformat(pub_str) if pub_str else datetime.now(timezone.utc)
    return NewsRecord(
        external_id=article.get("url"),
        data_source="GENERIC_WEB_SUMMARY",
        source_url=article.get("url"),
        published_at=published_at,
        title=article.get("title", ""),
        body=article.get("text"),
        extra={"publisher": article.get("publisher")},
    )


def yf_metrics_to_security_ext(
    metrics: dict[str, Any], ratios: dict[str, Any], security_id: int
) -> SecurityExtRecord:
    """Convert yfinance metrics + ratios dicts to SecurityExtRecord.

    Args:
        metrics: Normalised dict from ``YFinanceClient.get_key_metrics()``.
        ratios: Normalised dict from ``YFinanceClient.get_financial_ratios()``.
        security_id: FK to fin_markets.securities.

    Returns:
        SecurityExtRecord ready for insertion into fin_markets.security_exts.
    """
    return SecurityExtRecord(
        security_id=security_id,
        published_at=datetime.now(timezone.utc),
        pe_ratio=_dec(metrics.get("peRatio")),
        pb_ratio=_dec(metrics.get("pbRatio")),
        net_margin=_dec(ratios.get("netProfitMargin")),
        debt_to_equity=_dec(metrics.get("debtToEquity")),
        dividend_yield=_dec(metrics.get("dividendYield")),
    )


def yf_metrics_to_ext_aggreg(
    metrics: dict[str, Any], ratios: dict[str, Any], security_ext_id: int
) -> SecurityExtAggregRecord:
    """Convert yfinance metrics + ratios dicts to SecurityExtAggregRecord.

    Merges key_metrics and financial_ratios into a single aggregated record.
    Values already stored from profile are preserved via COALESCE on conflict.

    Args:
        metrics: Normalised dict from ``YFinanceClient.get_key_metrics()``.
        ratios: Normalised dict from ``YFinanceClient.get_financial_ratios()``.
        security_ext_id: FK to fin_markets.security_exts.

    Returns:
        SecurityExtAggregRecord ready for insertion.
    """
    return SecurityExtAggregRecord(
        security_ext_id=security_ext_id,
        published_at=datetime.now(timezone.utc),
        pe_forward=_dec(metrics.get("forwardPE")),
        ps_ratio=_dec(metrics.get("psRatio")),
        peg_ratio=_dec(metrics.get("pegRatio")),
        roe=_dec(metrics.get("roe")),
        roa=_dec(metrics.get("roa")),
        beta=_dec(metrics.get("beta")),
        gross_margin=_dec(ratios.get("grossProfitMargin")),
        operating_margin=_dec(ratios.get("operatingProfitMargin")),
        current_ratio=_dec(metrics.get("currentRatio")),
        quick_ratio=_dec(metrics.get("quickRatio")),
        payout_ratio=_dec(metrics.get("payoutRatio")),
    )


# ── Profile → security_exts + security_ext_aggregs ───────────────────────────

def fmp_profile_to_security_ext(profile: dict[str, Any], security_id: int) -> SecurityExtRecord:
    """Extract SecurityExtRecord from FMP company profile response.

    FMP profile contains market snapshot data (price, market cap, dividend, PE).
    Margins and revenue are not in the FMP profile; those come from key-metrics-ttm.

    Args:
        profile: Raw JSON from FMP ``/profile/{symbol}``.
        security_id: FK to fin_markets.securities.

    Returns:
        SecurityExtRecord populated from profile fields.
    """
    return SecurityExtRecord(
        security_id=security_id,
        published_at=datetime.now(timezone.utc),
        price=_dec(profile.get("price")),
        market_cap_usd=_dec(profile.get("mktCap")),
        pe_ratio=_dec(profile.get("pe")),
        eps_ttm=_dec(profile.get("eps")),
        dividend_yield=_dec(profile.get("lastDiv")),
        dividend_rate=_dec(profile.get("lastDiv")),
    )


def fmp_profile_to_ext_aggreg(profile: dict[str, Any], security_ext_id: int) -> SecurityExtAggregRecord:
    """Extract SecurityExtAggregRecord from FMP company profile response.

    Extracts beta, shares, analyst data available in the FMP profile.

    Args:
        profile: Raw JSON from FMP ``/profile/{symbol}``.
        security_ext_id: FK to fin_markets.security_exts.

    Returns:
        SecurityExtAggregRecord populated from profile fields.
    """
    return SecurityExtAggregRecord(
        security_ext_id=security_ext_id,
        published_at=datetime.now(timezone.utc),
        beta=_dec(profile.get("beta")),
        shares_outstanding=int(profile["sharesOutstanding"]) if profile.get("sharesOutstanding") else None,
        analyst_target_price=_dec(profile.get("dcfDiff")),  # FMP profile has dcf data but not analyst target
    )


def yf_profile_to_security_ext(profile: dict[str, Any], security_id: int) -> SecurityExtRecord:
    """Extract SecurityExtRecord from yfinance company profile dict.

    Maps all available snapshot fields from Ticker.info into the slow-changing
    security_exts table.

    Args:
        profile: Normalised dict from ``YFinanceClient.get_company_profile()``.
        security_id: FK to fin_markets.securities.

    Returns:
        SecurityExtRecord populated from profile fields.
    """
    return SecurityExtRecord(
        security_id=security_id,
        published_at=datetime.now(timezone.utc),
        price=_dec(profile.get("price")),
        market_cap_usd=_dec(profile.get("mktCap")),
        pe_ratio=_dec(profile.get("peRatioTTM")),
        pb_ratio=_dec(profile.get("pbRatioTTM")),
        eps_ttm=_dec(profile.get("eps")),
        net_margin=_dec(profile.get("profitMargins")),
        revenue_ttm=_dec(profile.get("totalRevenue")),
        debt_to_equity=_dec(profile.get("debtToEquity")),
        dividend_yield=_dec(profile.get("dividendYield")),
        dividend_rate=_dec(profile.get("dividendRate")),
        extra={
            "revenueGrowth": profile.get("revenueGrowth"),
            "earningsGrowth": profile.get("earningsGrowth"),
        },
    )


def yf_profile_to_ext_aggreg(profile: dict[str, Any], security_ext_id: int) -> SecurityExtAggregRecord:
    """Extract SecurityExtAggregRecord from yfinance company profile dict.

    Maps all available aggregated metrics from Ticker.info into the
    security_ext_aggregs table (valuation, profitability, balance sheet,
    ownership, and analyst consensus).

    Args:
        profile: Normalised dict from ``YFinanceClient.get_company_profile()``.
        security_ext_id: FK to fin_markets.security_exts.

    Returns:
        SecurityExtAggregRecord populated from profile fields.
    """
    return SecurityExtAggregRecord(
        security_ext_id=security_ext_id,
        published_at=datetime.now(timezone.utc),
        beta=_dec(profile.get("beta")),
        # valuation
        pe_forward=_dec(profile.get("forwardPE")),
        ps_ratio=_dec(profile.get("psRatioTTM")),
        peg_ratio=_dec(profile.get("pegRatio")),
        # profitability
        roe=_dec(profile.get("returnOnEquity")),
        roa=_dec(profile.get("returnOnAssets")),
        gross_margin=_dec(profile.get("grossMargins")),
        operating_margin=_dec(profile.get("operatingMargins")),
        # income / balance sheet
        eps_diluted=_dec(profile.get("epsDiluted")),
        ebitda_ttm=_dec(profile.get("ebitda")),
        net_income_ttm=_dec(profile.get("netIncomeToCommon")),
        total_debt=_dec(profile.get("totalDebt")),
        total_cash=_dec(profile.get("totalCash")),
        current_ratio=_dec(profile.get("currentRatio")),
        quick_ratio=_dec(profile.get("quickRatio")),
        book_value_ps=_dec(profile.get("bookValue")),
        # dividends
        payout_ratio=_dec(profile.get("payoutRatio")),
        # ownership
        shares_outstanding=int(profile["sharesOutstanding"]) if profile.get("sharesOutstanding") else None,
        float_shares=int(profile["floatShares"]) if profile.get("floatShares") else None,
        short_ratio=_dec(profile.get("shortRatio")),
        # analyst
        analyst_target_price=_dec(profile.get("targetMeanPrice")),
        analyst_count=int(profile["numberOfAnalystOpinions"]) if profile.get("numberOfAnalystOpinions") else None,
    )

