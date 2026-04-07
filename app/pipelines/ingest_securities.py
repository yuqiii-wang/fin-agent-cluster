"""Pipeline: Ingest securities from FMP API → fin_markets.securities + entities."""

import json
import logging
from typing import Any

from app.pipelines.base import BasePipeline
from app.quant_api.fmp import FMPClient
from app.quant_api.transforms import fmp_profile_to_security, fmp_profile_to_entity

logger = logging.getLogger(__name__)


class IngestSecuritiesPipeline(BasePipeline):
    """Fetch company profiles from FMP and upsert into fin_markets.securities and entities."""

    async def run(self, symbols: list[str], **kwargs: Any) -> dict[str, int]:
        """Ingest security profiles for a list of ticker symbols.

        Args:
            symbols: List of ticker symbols (e.g. ['AAPL', 'MSFT']).

        Returns:
            Dict with counts: {'securities': N, 'entities': N}.
        """
        settings = self._settings
        fmp = FMPClient(api_key=settings.FMP_API_KEY)
        sec_count = 0
        ent_count = 0

        try:
            for symbol in symbols:
                profile = await fmp.get_company_profile(symbol)
                if not profile:
                    logger.warning("No profile found for %s", symbol)
                    continue

                sec = fmp_profile_to_security(profile)
                await self._upsert_security(sec)
                sec_count += 1

                entity = fmp_profile_to_entity(profile)
                await self._upsert_entity(entity)
                ent_count += 1

        finally:
            await fmp.close()
            await self.close()

        logger.info("Ingested %d securities, %d entities", sec_count, ent_count)
        return {"securities": sec_count, "entities": ent_count}

    async def _upsert_security(self, sec: Any) -> None:
        """Upsert a security record into fin_markets.securities.

        Args:
            sec: SecurityRecord pydantic model.
        """
        await self._execute(
            """
            INSERT INTO fin_markets.securities (ticker, name, security_type, exchange, region, industry, description, extra)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (ticker, exchange) DO UPDATE SET
                name = EXCLUDED.name,
                security_type = EXCLUDED.security_type,
                region = EXCLUDED.region,
                industry = EXCLUDED.industry,
                description = EXCLUDED.description,
                extra = EXCLUDED.extra,
                updated_at = NOW()
            """,
            (sec.ticker, sec.name, sec.security_type, sec.exchange, sec.region,
             sec.industry, sec.description, json.dumps(sec.extra)),
        )

    async def _upsert_entity(self, entity: Any) -> None:
        """Upsert an entity record into fin_markets.entities.

        Args:
            entity: EntityRecord pydantic model.
        """
        await self._execute(
            """
            INSERT INTO fin_markets.entities (name, short_name, entity_type, region, website, description)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (entity.name, entity.short_name, entity.entity_type,
             entity.region, entity.website, entity.description),
        )
