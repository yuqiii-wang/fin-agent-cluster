"""Tasks package for prepare_industry_news node."""

from backend.langgraph.nodes.prepare_industry_news.tasks.propose_industry_news_topics import (
    propose_industry_news_topics,
    ProposeIndustryNewsTopicsInput,
    ProposeIndustryNewsTopicsOutput,
    STREAM_PROMPT_BUILDERS as _PINT_BUILDERS,
)

STREAM_PROMPT_BUILDERS: dict = {**_PINT_BUILDERS}

__all__ = [
    "propose_industry_news_topics",
    "ProposeIndustryNewsTopicsInput",
    "ProposeIndustryNewsTopicsOutput",
    "STREAM_PROMPT_BUILDERS",
]
