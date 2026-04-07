"""FundamentalsRepo — CRUD for fin_markets.security_exts and security_ext_aggregs."""

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos.base import BaseRepo
from app.models.markets.fundamentals import SecurityExtAggregRecord, SecurityExtRecord


class FundamentalsRepo(BaseRepo):
    """Repository for fin_markets.security_exts and fin_markets.security_ext_aggregs."""

    async def get_security_ext_today(self, security_id: int) -> dict[str, Any] | None:
        """Return today's security_exts snapshot with aggregs joined (if within 20 hours).

        Args:
            security_id: FK to fin_markets.securities.

        Returns:
            Combined row dict from security_exts + security_ext_aggregs, or ``None``.
        """
        rows = await self._execute(
            """
            SELECT se.*,
                   sa.beta, sa.pe_forward, sa.ps_ratio, sa.ev_ebitda, sa.peg_ratio,
                   sa.roe, sa.roa, sa.gross_margin, sa.operating_margin,
                   sa.eps_diluted, sa.ebitda_ttm, sa.net_income_ttm,
                   sa.total_debt, sa.total_cash, sa.current_ratio, sa.quick_ratio, sa.book_value_ps,
                   sa.payout_ratio,
                   sa.shares_outstanding, sa.float_shares, sa.short_ratio,
                   sa.analyst_target_price, sa.analyst_count
            FROM fin_markets.security_exts se
            LEFT JOIN fin_markets.security_ext_aggregs sa
                   ON sa.security_ext_id = se.id
            WHERE se.security_id = :security_id
              AND se.published_at >= NOW() AT TIME ZONE 'UTC' - INTERVAL '20 hours'
            ORDER BY se.published_at DESC
            LIMIT 1
            """,
            {"security_id": security_id},
        )
        return rows[0] if rows else None

    async def upsert_security_ext(self, ext: SecurityExtRecord) -> int | None:
        """Upsert a security_exts snapshot row, returning its id.

        COALESCE is used on conflict so partial updates (profile-only vs
        metrics-only) never overwrite already-populated columns with NULL.

        Args:
            ext: ``SecurityExtRecord`` to persist.

        Returns:
            The row's ``id``, or ``None`` on failure.
        """
        rows = await self._execute(
            """
            INSERT INTO fin_markets.security_exts
                (security_id, published_at, price, market_cap_usd, pe_ratio,
                 pb_ratio, eps_ttm, dividend_yield, dividend_rate,
                 net_margin, revenue_ttm, debt_to_equity)
            VALUES (:security_id, :published_at, :price, :market_cap_usd, :pe_ratio,
                    :pb_ratio, :eps_ttm, :dividend_yield, :dividend_rate,
                    :net_margin, :revenue_ttm, :debt_to_equity)
            ON CONFLICT (security_id, published_at) DO UPDATE SET
                price          = COALESCE(EXCLUDED.price,
                                          fin_markets.security_exts.price),
                market_cap_usd = COALESCE(EXCLUDED.market_cap_usd,
                                          fin_markets.security_exts.market_cap_usd),
                pe_ratio       = COALESCE(EXCLUDED.pe_ratio,
                                          fin_markets.security_exts.pe_ratio),
                pb_ratio       = COALESCE(EXCLUDED.pb_ratio,
                                          fin_markets.security_exts.pb_ratio),
                eps_ttm        = COALESCE(EXCLUDED.eps_ttm,
                                          fin_markets.security_exts.eps_ttm),
                dividend_yield = COALESCE(EXCLUDED.dividend_yield,
                                          fin_markets.security_exts.dividend_yield),
                dividend_rate  = COALESCE(EXCLUDED.dividend_rate,
                                          fin_markets.security_exts.dividend_rate),
                net_margin     = COALESCE(EXCLUDED.net_margin,
                                          fin_markets.security_exts.net_margin),
                revenue_ttm    = COALESCE(EXCLUDED.revenue_ttm,
                                          fin_markets.security_exts.revenue_ttm),
                debt_to_equity = COALESCE(EXCLUDED.debt_to_equity,
                                          fin_markets.security_exts.debt_to_equity)
            RETURNING id
            """,
            {
                "security_id": ext.security_id,
                "published_at": ext.published_at,
                "price": ext.price,
                "market_cap_usd": ext.market_cap_usd,
                "pe_ratio": ext.pe_ratio,
                "pb_ratio": ext.pb_ratio,
                "eps_ttm": ext.eps_ttm,
                "dividend_yield": ext.dividend_yield,
                "dividend_rate": ext.dividend_rate,
                "net_margin": ext.net_margin,
                "revenue_ttm": ext.revenue_ttm,
                "debt_to_equity": ext.debt_to_equity,
            },
        )
        return rows[0]["id"] if rows else None

    async def upsert_security_ext_aggreg(self, aggreg: SecurityExtAggregRecord) -> None:
        """Upsert a security_ext_aggregs row.

        Covers profile-sourced fields (beta, shares, analyst), metrics-sourced
        fields (ratios, margins), and balance-sheet highlights in a single upsert
        so callers never overwrite each other's data via COALESCE.

        Args:
            aggreg: ``SecurityExtAggregRecord`` to persist.
        """
        await self._execute(
            """
            INSERT INTO fin_markets.security_ext_aggregs
                (security_ext_id, published_at, beta, pe_forward,
                 shares_outstanding, float_shares, short_ratio,
                 analyst_target_price, analyst_count,
                 ps_ratio, ev_ebitda, peg_ratio,
                 roe, roa, gross_margin, operating_margin,
                 eps_diluted, ebitda_ttm, net_income_ttm,
                 total_debt, total_cash, current_ratio, quick_ratio, book_value_ps,
                 payout_ratio)
            VALUES (:security_ext_id, :published_at, :beta, :pe_forward,
                    :shares_outstanding, :float_shares, :short_ratio,
                    :analyst_target_price, :analyst_count,
                    :ps_ratio, :ev_ebitda, :peg_ratio,
                    :roe, :roa, :gross_margin, :operating_margin,
                    :eps_diluted, :ebitda_ttm, :net_income_ttm,
                    :total_debt, :total_cash, :current_ratio, :quick_ratio, :book_value_ps,
                    :payout_ratio)
            ON CONFLICT (security_ext_id) DO UPDATE SET
                beta                 = COALESCE(EXCLUDED.beta,
                                                fin_markets.security_ext_aggregs.beta),
                pe_forward           = COALESCE(EXCLUDED.pe_forward,
                                                fin_markets.security_ext_aggregs.pe_forward),
                shares_outstanding   = COALESCE(EXCLUDED.shares_outstanding,
                                                fin_markets.security_ext_aggregs.shares_outstanding),
                float_shares         = COALESCE(EXCLUDED.float_shares,
                                                fin_markets.security_ext_aggregs.float_shares),
                short_ratio          = COALESCE(EXCLUDED.short_ratio,
                                                fin_markets.security_ext_aggregs.short_ratio),
                analyst_target_price = COALESCE(EXCLUDED.analyst_target_price,
                                                fin_markets.security_ext_aggregs.analyst_target_price),
                analyst_count        = COALESCE(EXCLUDED.analyst_count,
                                                fin_markets.security_ext_aggregs.analyst_count),
                ps_ratio             = COALESCE(EXCLUDED.ps_ratio,
                                                fin_markets.security_ext_aggregs.ps_ratio),
                ev_ebitda            = COALESCE(EXCLUDED.ev_ebitda,
                                                fin_markets.security_ext_aggregs.ev_ebitda),
                peg_ratio            = COALESCE(EXCLUDED.peg_ratio,
                                                fin_markets.security_ext_aggregs.peg_ratio),
                roe                  = COALESCE(EXCLUDED.roe,
                                                fin_markets.security_ext_aggregs.roe),
                roa                  = COALESCE(EXCLUDED.roa,
                                                fin_markets.security_ext_aggregs.roa),
                gross_margin         = COALESCE(EXCLUDED.gross_margin,
                                                fin_markets.security_ext_aggregs.gross_margin),
                operating_margin     = COALESCE(EXCLUDED.operating_margin,
                                                fin_markets.security_ext_aggregs.operating_margin),
                eps_diluted          = COALESCE(EXCLUDED.eps_diluted,
                                                fin_markets.security_ext_aggregs.eps_diluted),
                ebitda_ttm           = COALESCE(EXCLUDED.ebitda_ttm,
                                                fin_markets.security_ext_aggregs.ebitda_ttm),
                net_income_ttm       = COALESCE(EXCLUDED.net_income_ttm,
                                                fin_markets.security_ext_aggregs.net_income_ttm),
                total_debt           = COALESCE(EXCLUDED.total_debt,
                                                fin_markets.security_ext_aggregs.total_debt),
                total_cash           = COALESCE(EXCLUDED.total_cash,
                                                fin_markets.security_ext_aggregs.total_cash),
                current_ratio        = COALESCE(EXCLUDED.current_ratio,
                                                fin_markets.security_ext_aggregs.current_ratio),
                quick_ratio          = COALESCE(EXCLUDED.quick_ratio,
                                                fin_markets.security_ext_aggregs.quick_ratio),
                book_value_ps        = COALESCE(EXCLUDED.book_value_ps,
                                                fin_markets.security_ext_aggregs.book_value_ps),
                payout_ratio         = COALESCE(EXCLUDED.payout_ratio,
                                                fin_markets.security_ext_aggregs.payout_ratio)
            """,
            {
                "security_ext_id": aggreg.security_ext_id,
                "published_at": aggreg.published_at,
                "beta": aggreg.beta,
                "pe_forward": aggreg.pe_forward,
                "shares_outstanding": aggreg.shares_outstanding,
                "float_shares": aggreg.float_shares,
                "short_ratio": aggreg.short_ratio,
                "analyst_target_price": aggreg.analyst_target_price,
                "analyst_count": aggreg.analyst_count,
                "ps_ratio": aggreg.ps_ratio,
                "ev_ebitda": aggreg.ev_ebitda,
                "peg_ratio": aggreg.peg_ratio,
                "roe": aggreg.roe,
                "roa": aggreg.roa,
                "gross_margin": aggreg.gross_margin,
                "operating_margin": aggreg.operating_margin,
                "eps_diluted": aggreg.eps_diluted,
                "ebitda_ttm": aggreg.ebitda_ttm,
                "net_income_ttm": aggreg.net_income_ttm,
                "total_debt": aggreg.total_debt,
                "total_cash": aggreg.total_cash,
                "current_ratio": aggreg.current_ratio,
                "quick_ratio": aggreg.quick_ratio,
                "book_value_ps": aggreg.book_value_ps,
                "payout_ratio": aggreg.payout_ratio,
            },
        )
