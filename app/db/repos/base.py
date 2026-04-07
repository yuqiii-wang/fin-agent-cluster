"""BaseRepo — shared SQLAlchemy session wrapper for all repository classes."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class BaseRepo:
    """Thin wrapper around an ``AsyncSession`` exposing a single ``_execute`` helper.

    All repository classes inherit from ``BaseRepo`` and call ``self._execute``
    for every SQL statement.  Rows are fetched *before* committing so the
    ``RETURNING`` clause works correctly in all providers.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with a shared SQLAlchemy async session.

        Args:
            session: Open ``AsyncSession`` managed by the caller (e.g. the
                     service layer).  The caller is responsible for closing it.
        """
        self._s = session

    async def _execute(
        self, sql: str, params: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        """Execute a parameterised SQL statement and return all rows.

        Named parameters use ``:name`` syntax (SQLAlchemy ``text()`` style).
        Rows are fetched into Python memory before the statement is committed,
        so ``RETURNING`` clauses are fully supported.

        Args:
            sql: SQL string with ``:name`` placeholders.
            params: Dict of named parameters.

        Returns:
            List of row dicts.  Empty list for non-``SELECT`` statements
            without a ``RETURNING`` clause.
        """
        result = await self._s.execute(text(sql), params or {})
        rows: list[dict[str, Any]] = []
        if result.returns_rows:
            rows = [dict(r) for r in result.mappings().all()]
        await self._s.commit()
        return rows
