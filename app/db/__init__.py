"""Database access layer — SQLAlchemy-based repository classes.

Usage::

    from app.db import SecurityRepo, FundamentalsRepo, TradeRepo, NewsRepo
    from app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as session:
        sec_repo = SecurityRepo(session)
        row = await sec_repo.get_security("AAPL")
"""

from app.db.repos.fundamentals import FundamentalsRepo
from app.db.repos.news import NewsRepo
from app.db.repos.securities import SecurityRepo
from app.db.repos.trades import TradeRepo

__all__ = ["SecurityRepo", "FundamentalsRepo", "TradeRepo", "NewsRepo"]
