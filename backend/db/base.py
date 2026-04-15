"""Shared SQLAlchemy declarative base — imported by all ORM model modules."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all ORM models in this project."""
