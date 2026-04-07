"""SecurityRepo — CRUD for fin_markets.securities and fin_markets.entities."""

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos.base import BaseRepo
from app.models.markets.securities import EntityRecord, SecurityRecord


class SecurityRepo(BaseRepo):
    """Repository for fin_markets.securities and fin_markets.entities tables."""

    async def get_security(self, ticker: str) -> dict[str, Any] | None:
        """Read an active security row by ticker.

        Args:
            ticker: Ticker symbol (e.g. ``'AAPL'``).

        Returns:
            Row dict or ``None`` if not found.
        """
        rows = await self._execute(
            """
            SELECT * FROM fin_markets.securities
            WHERE ticker = :ticker AND is_active = TRUE
            LIMIT 1
            """,
            {"ticker": ticker},
        )
        return rows[0] if rows else None

    async def get_table_columns(self, schema: str, table: str) -> set[str]:
        """Return the set of column names for a table (schema introspection).

        Args:
            schema: Postgres schema name (e.g. ``'fin_markets'``).
            table: Table name (e.g. ``'security_exts'``).

        Returns:
            Set of column name strings.
        """
        rows = await self._execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = :schema AND table_name = :table
            """,
            {"schema": schema, "table": table},
        )
        return {r["column_name"] for r in rows}

    async def upsert_security(self, sec: SecurityRecord) -> None:
        """Upsert a security record into fin_markets.securities.

        Args:
            sec: Normalised ``SecurityRecord``.
        """
        await self._execute(
            """
            INSERT INTO fin_markets.securities
                (ticker, name, security_type, exchange, region, industry, description, extra)
            VALUES (:ticker, :name, :security_type, :exchange, :region, :industry,
                    :description, CAST(:extra AS jsonb))
            ON CONFLICT (ticker, exchange) DO UPDATE SET
                name          = EXCLUDED.name,
                security_type = EXCLUDED.security_type,
                region        = EXCLUDED.region,
                industry      = EXCLUDED.industry,
                description   = EXCLUDED.description,
                extra         = EXCLUDED.extra,
                updated_at    = NOW()
            """,
            {
                "ticker": sec.ticker,
                "name": sec.name,
                "security_type": sec.security_type,
                "exchange": sec.exchange,
                "region": sec.region,
                "industry": sec.industry,
                "description": sec.description,
                "extra": json.dumps(sec.extra),
            },
        )

    async def upsert_entity(self, entity: EntityRecord) -> None:
        """Upsert an entity record into fin_markets.entities.

        Args:
            entity: Normalised ``EntityRecord``.
        """
        await self._execute(
            """
            INSERT INTO fin_markets.entities
                (name, short_name, entity_type, region, industry,
                 website, description, established_at)
            VALUES (:name, :short_name, :entity_type, :region, :industry,
                    :website, :description, :established_at)
            ON CONFLICT (name, entity_type) DO UPDATE SET
                short_name     = EXCLUDED.short_name,
                region         = EXCLUDED.region,
                industry       = COALESCE(EXCLUDED.industry,
                                          fin_markets.entities.industry),
                website        = EXCLUDED.website,
                description    = EXCLUDED.description,
                established_at = COALESCE(EXCLUDED.established_at,
                                          fin_markets.entities.established_at)
            """,
            {
                "name": entity.name,
                "short_name": entity.short_name,
                "entity_type": entity.entity_type,
                "region": entity.region,
                "industry": entity.industry,
                "website": entity.website,
                "description": entity.description,
                "established_at": entity.established_at,
            },
        )
