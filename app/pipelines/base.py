"""Base pipeline class with shared DB access and quant API client."""

import logging
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

from app.config import get_settings

logger = logging.getLogger(__name__)


class BasePipeline:
    """Base class providing shared async DB connection for all pipelines.

    Subclasses implement run() with their specific transform logic.
    """

    def __init__(self) -> None:
        """Initialize pipeline with settings."""
        self._settings = get_settings()
        self._conn: AsyncConnection | None = None

    async def _get_conn(self) -> AsyncConnection:
        """Get or create a reusable DB connection.

        Returns:
            Async PostgreSQL connection with dict row factory.
        """
        if self._conn is None or self._conn.closed:
            self._conn = await AsyncConnection.connect(
                self._settings.DATABASE_URL,
                autocommit=True,
                row_factory=dict_row,
            )
        return self._conn

    async def _execute(self, query: str, params: tuple | None = None) -> list[dict[str, Any]]:
        """Execute a SQL query and return all rows as dicts.

        Args:
            query: SQL query string with %s placeholders.
            params: Query parameters.

        Returns:
            List of row dicts.
        """
        conn = await self._get_conn()
        async with conn.cursor() as cur:
            await cur.execute(query, params)
            if cur.description:
                return await cur.fetchall()
            return []

    async def _execute_many(self, query: str, params_seq: list[tuple]) -> None:
        """Execute a SQL query for each parameter tuple in the sequence.

        Args:
            query: SQL query string with %s placeholders.
            params_seq: List of parameter tuples.
        """
        conn = await self._get_conn()
        async with conn.cursor() as cur:
            for params in params_seq:
                await cur.execute(query, params)

    async def close(self) -> None:
        """Close the DB connection."""
        if self._conn and not self._conn.closed:
            await self._conn.close()

    async def run(self, **kwargs: Any) -> Any:
        """Execute the pipeline. Override in subclasses.

        Args:
            **kwargs: Pipeline-specific parameters.
        """
        raise NotImplementedError
