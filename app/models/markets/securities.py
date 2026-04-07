"""Securities and indexes — master reference tables (fin_markets schema)."""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class SecurityRecord(BaseModel):
    """Pydantic model for fin_markets.securities rows."""

    id: Optional[int] = None
    ticker: str
    name: str
    parent_security_id: Optional[int] = None
    security_type: str
    exchange: Optional[str] = None
    region: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True
    extra: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class IndexRecord(BaseModel):
    """Pydantic model for fin_markets.indexes rows."""

    id: Optional[int] = None
    security_id: int
    name: str
    short_name: Optional[str] = None
    description: Optional[str] = None
    region: Optional[str] = None
    is_active: bool = True
    extra: dict = Field(default_factory=dict)

    model_config = {"from_attributes": True}


class EntityRecord(BaseModel):
    """Pydantic model for fin_markets.entities rows."""

    id: Optional[int] = None
    name: str
    short_name: Optional[str] = None
    entity_type: str
    parent_id: Optional[int] = None
    region: Optional[str] = None
    industry: Optional[str] = None
    lei: Optional[str] = None
    website: Optional[str] = None
    description: Optional[str] = None
    is_active: bool = True
    extra: dict = Field(default_factory=dict)
    established_at: Optional[date] = None

    model_config = {"from_attributes": True}
