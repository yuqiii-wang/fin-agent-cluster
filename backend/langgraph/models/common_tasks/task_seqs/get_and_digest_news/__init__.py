"""get_and_digest_news -- TaskSeq pipeline: fetch raw news/info then LLM-digest into news_stats.

Orchestration
-------------
1. ``get_news``    -- fetch news and web-search snippets via NewsClient (DDGS), cache in ``input_raw``.
2. ``do_summary``  -- LLM-classify each article (soft failure).
3. ``do_emb``      -- embed AI summaries (soft failure).
4. ``digest_news`` -- read from input_raw, combine enrichment, upsert to news_stats, render Markdown.
"""

from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news.get_news import (
    GetNewsInput,
    GetNewsOutput,
    get_news,
    HANDLERS as _GN_HANDLERS,
)
from backend.langgraph.models.common_tasks.do_summary import (
    DoSummaryInput,
    DoSummaryOutput,
    SummaryRecord,
    do_summary,
    HANDLERS as _DS_HANDLERS,
    STREAM_PROMPT_BUILDERS as _DS_SPB,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news.do_emb import (
    DoEmbInput,
    DoEmbOutput,
    do_emb,
    HANDLERS as _DE_HANDLERS,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news.digest_news import (
    DigestNewsInput,
    DigestNewsOutput,
    digest_news,
    HANDLERS as _DN_HANDLERS,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news.models import (
    GetAndDigestNewsInput,
    GetAndDigestNewsOutput,
)
from backend.langgraph.models.common_tasks.task_seqs.get_and_digest_news.seq import (
    get_and_digest_news,
)

HANDLERS: dict = {**_GN_HANDLERS, **_DS_HANDLERS, **_DE_HANDLERS, **_DN_HANDLERS}
STREAM_PROMPT_BUILDERS: dict = {**_DS_SPB}

__all__ = [
    "GetNewsInput",
    "GetNewsOutput",
    "get_news",
    "DoSummaryInput",
    "DoSummaryOutput",
    "SummaryRecord",
    "do_summary",
    "DoEmbInput",
    "DoEmbOutput",
    "do_emb",
    "DigestNewsInput",
    "DigestNewsOutput",
    "digest_news",
    "GetAndDigestNewsInput",
    "GetAndDigestNewsOutput",
    "get_and_digest_news",
    "HANDLERS",
    "STREAM_PROMPT_BUILDERS",
]
