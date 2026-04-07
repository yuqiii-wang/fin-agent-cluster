"""AnalysisSnapshotRepo — CRUD for fin_strategies.analysis_snapshots."""

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repos.base import BaseRepo

# Default staleness windows per node (hours)
_STALE_HOURS: dict[str, int] = {
    "market_data_collector": 4,
    "fundamental_analyzer": 20,
    "technical_analyzer": 4,
    "news_collector": 4,
    "risk_assessor": 8,
    "report_generator": 8,
}
_DEFAULT_STALE_HOURS = 8


class AnalysisSnapshotRepo(BaseRepo):
    """Repository for fin_strategies.analysis_snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        """Initialise with a shared SQLAlchemy async session.

        Args:
            session: Open ``AsyncSession`` managed by the caller.
        """
        super().__init__(session)

    async def get_fresh(self, security_id: int, node_name: str) -> str | None:
        """Return the most recent non-stale snapshot content, or None.

        Args:
            security_id: FK to fin_markets.securities.
            node_name: LangGraph node identifier string.

        Returns:
            LLM output text if a fresh snapshot exists, else ``None``.
        """
        rows = await self._execute(
            """
            SELECT content
            FROM fin_strategies.analysis_snapshots
            WHERE security_id = :security_id
              AND node_name   = :node_name
              AND stale_after > NOW() AT TIME ZONE 'UTC'
            ORDER BY published_at DESC
            LIMIT 1
            """,
            {"security_id": security_id, "node_name": node_name},
        )
        return rows[0]["content"] if rows else None

    async def save(
        self,
        security_id: int,
        node_name: str,
        content: str,
        stale_hours: int | None = None,
        extra: dict[str, Any] | None = None,
        token_count: int | None = None,
    ) -> int | None:
        """Insert a new analysis snapshot row.

        Args:
            security_id: FK to fin_markets.securities.
            node_name: LangGraph node identifier string.
            content: Full LLM output text.
            stale_hours: Override staleness window. Defaults to per-node setting.
            extra: Optional extra metadata (prompt params, model version, etc.).
            token_count: Optional total token count for cost tracking.

        Returns:
            The new row ``id``, or ``None`` on failure.
        """
        hours = stale_hours or _STALE_HOURS.get(node_name, _DEFAULT_STALE_HOURS)
        now = datetime.now(timezone.utc)
        stale_after = now + timedelta(hours=hours)
        rows = await self._execute(
            """
            INSERT INTO fin_strategies.analysis_snapshots
                (security_id, node_name, published_at, stale_after,
                 content, token_count, extra)
            VALUES (:security_id, :node_name, :published_at, :stale_after,
                    :content, :token_count, :extra::jsonb)
            ON CONFLICT (security_id, node_name, published_at) DO NOTHING
            RETURNING id
            """,
            {
                "security_id": security_id,
                "node_name": node_name,
                "published_at": now,
                "stale_after": stale_after,
                "content": content,
                "token_count": token_count,
                "extra": str(extra or {}).replace("'", '"'),
            },
        )
        return rows[0]["id"] if rows else None
