"""Public API for backend.resources.info.

Provides :class:`InfoClient` for DDGS-backed web search and
:class:`InfoResult` as the typed search-result model.
"""

from backend.resources.info.client import InfoClient
from backend.resources.info.models import InfoResult

__all__ = ["InfoClient", "InfoResult"]
