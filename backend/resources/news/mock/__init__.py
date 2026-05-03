"""Mock text data for the news provider.

Exports
-------
"MOCK_NEWS" : list[dict]
    List of mock news article dicts compatible with
    :class:`~backend.resources.news.models.NewsArticle`.
"""

from __future__ import annotations

from backend.resources.news.mock.text import MOCK_NEWS

__all__ = ["MOCK_NEWS"]
