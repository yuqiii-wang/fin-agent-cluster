"""NewsContext: news search query fields for market data collection."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class NewsContext(BaseModel):
    """News search queries for all research angles derived from the user query."""

    model_config = ConfigDict(extra="ignore")

    query_company_news: str = Field("", description="Recent company-specific news and events")
    query_financial_report: str = Field("", description="Latest financial reports and earnings")
    query_global_news: str = Field("", description="Global macro news affecting the ticker")
    query_industry_news: str = Field("", description="Industry/sector trends and analyst outlook")
    query_region_gov_policies: str = Field("", description="Government policies, regulation, tariffs")

    @classmethod
    def from_basics(
        cls,
        ticker: str,
        security_name: str,
        industry: str,
        region: str,
    ) -> "NewsContext":
        """Build NewsContext from static templates using core identity fields.

        Args:
            ticker:        Primary ticker symbol, e.g. ``'AAPL'``.
            security_name: Full company or security name.
            industry:      Industry/sector description.
            region:        Region name, e.g. ``'United States'``.

        Returns:
            :class:`NewsContext` with all query fields populated from templates.
        Note: ticker_indexes is not used in news queries.
        """
        name_part = f"{security_name} {ticker}".strip() if security_name else ticker
        return cls(
            query_company_news=(
                f"{name_part} recent news corporate events management changes earnings"
            ),
            query_financial_report=(
                f"{name_part} latest earnings report revenue EPS forward guidance"
            ),
            query_global_news=(
                f"global macro conditions rates inflation geopolitics impact {name_part}"
            ),
            query_industry_news=(
                f"{industry} sector trends competitive landscape analyst ratings {name_part}"
            ),
            query_region_gov_policies=(
                f"government policy regulation tariffs antitrust {industry} sector"
                f" {name_part} {region}".rstrip()
            ),
        )
