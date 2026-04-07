"""News articles, extensions, and topic taxonomy (fin_markets schema)."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import SentimentLevel


class NewsRecord(BaseModel):
    """Pydantic model for fin_markets.news rows."""

    id: Optional[int] = None
    external_id: Optional[str] = None
    data_source: Optional[str] = None
    source_url: Optional[str] = None
    published_at: datetime
    title: str
    subtitle: Optional[str] = None
    body: Optional[str] = None
    category: Optional[str] = None
    industry: Optional[str] = None
    region: Optional[str] = None
    tags: Optional[list[str]] = None
    extra: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class NewsExtRecord(BaseModel):
    """Pydantic model for fin_markets.news_exts rows (AI analysis per article)."""

    id: Optional[int] = None
    news_id: Optional[int] = None
    published_at: datetime
    sentiment_level: Optional[SentimentLevel] = None
    summary: Optional[str] = None
    news_coverage: Optional[str] = None
    relevance_score: Optional[Decimal] = None
    confidence: Optional[Decimal] = None
    impacted_industries: Optional[list[str]] = None
    knowledge_graph: Optional[dict] = None

    model_config = {"from_attributes": True}


class NewsTopicRecord(BaseModel):
    """Pydantic model for fin_markets.news_topics rows (hierarchical topic tree)."""

    id: Optional[int] = None
    parent_id: Optional[int] = None
    name: str
    slug: str
    path: str  # ltree stored as string
    level: int = 0
    description: Optional[str] = None
    num_data_sources: int = 0
    extra: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}
