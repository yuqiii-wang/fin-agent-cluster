"""crawl_url -- NodeTask: fetch a web page and extract links.

Uses :mod:`backend.httpx_client` to fetch the target URL and Python's stdlib
``html.parser`` to extract hyperlinks from the response body.
No extra dependencies are required.

Execution layers
----------------
LangGraph layer (``_crawl_url_task`` decorated with ``@task``):
    Calls ``create_task(..., view_type="WebRequest")``, delegates to the Celery
    completion worker, and returns a ``TaskOutput``.

Celery layer (``_handler``):
    1. Validates the URL (must be http/https).
    2. Fetches the page with :func:`~backend.httpx_client.make_web_browser_async_client`
       (follow redirects, timeout, browser headers).
    3. Extracts hyperlinks via ``html.parser``.
    4. Returns serialised :class:`CrawlUrlOutput`.

Public exports
--------------
``crawl_url``       -- ``NodeTask`` instance.
``CrawlUrlInput``   -- Pydantic input model.
``CrawlUrlOutput``  -- Pydantic output model.
``HANDLERS``        -- dict slice for ``backend.langgraph.nodes.HANDLERS``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from langgraph.func import task
from pydantic import BaseModel, Field, field_validator

from backend.celery_task.workers.task_delegation import delegate_completion
from backend.db.postgres import raw_conn
from backend.db.postgres.queries.fin_markets_input_raw import InputRawSQL
from _shared.httpx_client import RequestError, make_web_browser_async_client
from backend.langgraph.lifecycle import complete_task, create_task
from backend.langgraph.models.common_tasks.errors.codes import (
    WEB_TASK_FETCH_ERROR,
    WEB_TASK_INVALID_URL,
)
from backend.langgraph.models.models import NodeContext, TaskInput, TaskOutput
from backend.langgraph.models.task import NodeTask

logger = logging.getLogger(__name__)

_TASK_NAME = "crawl_url"
_FETCH_TIMEOUT_SECONDS = 30
_MAX_LINKS_DEFAULT = 50
_SOURCE = "web_crawl"
_METHOD = "crawl_url"
_NODE_NAME = "common_tasks/crawl_url"
_CACHE_TTL_HOURS = 4
_CACHE_TTL_SECONDS = _CACHE_TTL_HOURS * 3600


def _make_cache_key(url: str) -> str:
    """Compute a deterministic SHA-256 cache key for ``input_raw`` lookup.

    Args:
        url: The fully-qualified URL to crawl.

    Returns:
        Hex-encoded 64-character SHA-256 digest.
    """
    payload = json.dumps({"source": _SOURCE, "method": _METHOD, "url": url}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Internal HTML link extractor
# ---------------------------------------------------------------------------


class _LinkExtractor(HTMLParser):
    """Minimal HTML parser that collects ``href`` values from ``<a>`` tags."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self._base_url = base_url
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Collect absolute URLs from anchor href attributes."""
        if tag != "a":
            return
        for name, value in attrs:
            if name == "href" and value:
                absolute = urljoin(self._base_url, value.strip())
                parsed = urlparse(absolute)
                if parsed.scheme in ("http", "https"):
                    self.links.append(absolute)


def _extract_links(html: str, base_url: str, max_links: int) -> list[str]:
    """Extract up to *max_links* unique http/https links from *html*.

    Args:
        html:      Raw HTML string.
        base_url:  Base URL used to resolve relative hrefs.
        max_links: Maximum number of unique links to return.

    Returns:
        Deduplicated list of absolute http/https URLs (insertion-ordered).
    """
    extractor = _LinkExtractor(base_url)
    try:
        extractor.feed(html)
    except Exception:
        pass  # best-effort; broken HTML is fine
    seen: set[str] = set()
    unique: list[str] = []
    for link in extractor.links:
        if link not in seen:
            seen.add(link)
            unique.append(link)
        if len(unique) >= max_links:
            break
    return unique


# ---------------------------------------------------------------------------
# Input / output models
# ---------------------------------------------------------------------------


class CrawlUrlInput(BaseModel):
    """Input for the crawl_url task.

    Attributes:
        url:       HTTP/HTTPS URL to fetch.
        max_links: Maximum number of unique links to extract from the page.
                   Defaults to 50.
        thread_id: LangGraph thread ID; forwarded to ``input_raw`` for provenance.
        node_name: Calling node name; forwarded to ``input_raw`` for provenance.
    """

    url: str = Field(description="HTTP/HTTPS URL to crawl.")
    max_links: int = Field(
        default=_MAX_LINKS_DEFAULT,
        ge=0,
        le=500,
        description="Maximum number of unique links to extract from the page.",
    )
    thread_id: str | None = Field(default=None, description="Thread ID for input_raw provenance.")
    node_name: str = Field(default=_NODE_NAME, description="Node name for input_raw provenance.")

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        """Reject non-http/https URLs at model-validation time."""
        v = v.strip()
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                f"[{WEB_TASK_INVALID_URL}] url must use http or https scheme, got: {v!r}"
            )
        return v


class CrawlUrlOutput(BaseModel):
    """Output from the crawl_url task.

    Attributes:
        url:          Final URL after redirects.
        status_code:  HTTP response status code.
        title:        Page title extracted from ``<title>`` tag, or empty string.
        raw_html:     Full response body (HTML string).
        links:        Unique absolute links extracted from the page (up to max_links).
        content_type: ``Content-Type`` header value from the response.
        from_cache:   ``True`` when served from the ``input_raw`` cache.
    """

    url: str = Field(description="Final URL after any HTTP redirects.")
    status_code: int = Field(description="HTTP response status code.")
    title: str = Field(default="", description="Page title from <title> tag.")
    raw_html: str = Field(description="Full HTML response body.")
    links: list[str] = Field(
        default_factory=list,
        description="Unique absolute links extracted from the page.",
    )
    content_type: str = Field(default="", description="Content-Type header from the response.")
    from_cache: bool = Field(default=False, description="True when served from input_raw cache.")


# ---------------------------------------------------------------------------
# Celery layer -- business logic
# ---------------------------------------------------------------------------


async def _handler(payload: dict) -> dict:
    """Fetch a URL and extract links using httpx.

    Args:
        payload: Serialised :class:`CrawlUrlInput` dict.

    Returns:
        Serialised :class:`CrawlUrlOutput` dict.

    Raises:
        ValueError:    URL is not http/https.
        RuntimeError:  HTTP fetch failed (network error or non-2xx/3xx status).
    """
    inp = CrawlUrlInput.model_validate(payload)

    async with make_web_browser_async_client() as client:
        try:
            response = await client.get(inp.url)
        except RequestError as exc:
            raise RuntimeError(
                f"[{WEB_TASK_FETCH_ERROR}] HTTP request failed for {inp.url!r}: {exc}"
            ) from exc

    if response.status_code >= 400:
        raise RuntimeError(
            f"[{WEB_TASK_FETCH_ERROR}] Server returned status {response.status_code} "
            f"for {str(response.url)!r}"
        )

    final_url = str(response.url)
    raw_html = response.text
    content_type = response.headers.get("content-type", "")

    links = _extract_links(raw_html, base_url=final_url, max_links=inp.max_links)
    title = _extract_title(raw_html)

    output = CrawlUrlOutput(
        url=final_url,
        status_code=response.status_code,
        title=title,
        raw_html=raw_html,
        links=links,
        content_type=content_type,
    )
    cache_key = _make_cache_key(inp.url)
    try:
        async with raw_conn() as conn:
            await conn.execute(
                InputRawSQL.INSERT,
                (
                    inp.thread_id,
                    inp.node_name,
                    "",
                    _SOURCE,
                    _METHOD,
                    cache_key,
                    _CACHE_TTL_SECONDS,
                    json.dumps({"url": inp.url, "max_links": inp.max_links}),
                    json.dumps(output.model_dump(mode="json")),
                ),
            )
    except Exception as cache_exc:
        logger.error(
            "crawl_url: failed to insert input_raw cache for url=%r: %s",
            inp.url, cache_exc,
        )
    return output.model_dump()


def _extract_title(html: str) -> str:
    """Extract the text content of the first ``<title>`` element.

    Args:
        html: Raw HTML string.

    Returns:
        Title text stripped of whitespace, or empty string if not found.
    """
    import re

    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


# ---------------------------------------------------------------------------
# LangGraph layer -- @task
# ---------------------------------------------------------------------------


@task
async def _crawl_url_task(
    task_input: TaskInput[CrawlUrlInput],
) -> TaskOutput[CrawlUrlOutput]:
    """LangGraph @task: fetch a URL and extract links via the Celery completion worker.

    Args:
        task_input: Typed envelope with :class:`~backend.langgraph.models.models.TaskContext`
                    and :class:`CrawlUrlInput` content.

    Returns:
        :class:`~backend.langgraph.models.models.TaskOutput` wrapping
        :class:`CrawlUrlOutput`.
    """
    ctx = task_input.ctx
    payload = task_input.content.model_dump(mode="json")
    payload["thread_id"] = ctx.thread_id
    payload["node_name"] = ctx.node_name

    await create_task(
        ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name, payload,
        view_type="WebRequest",
    )
    try:
        result = await delegate_completion(
            thread_id=ctx.thread_id,
            task_id=ctx.task_id,
            node_id=ctx.node_id,
            node_name=ctx.node_name,
            task_name=ctx.task_name,
            payload=payload,
        )
        output = CrawlUrlOutput.model_validate(result)
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data=output.model_dump(mode="json"),
            view_type="WebRequest",
        )
        return TaskOutput(ctx=ctx, content=output)
    except Exception as exc:
        await complete_task(
            ctx.thread_id, ctx.node_id, ctx.node_name, ctx.task_id, ctx.task_name,
            output_data={"url": task_input.content.url},
            failed=True, error=str(exc), view_type="WebRequest",
        )
        raise


async def _crawl_url_pg_cache(
    inp: CrawlUrlInput, ctx: NodeContext
) -> CrawlUrlOutput | None:
    """Check ``input_raw`` for a recent crawl result for the same URL.

    Queries ``InputRawSQL.GET_CACHED`` with the per-row 4-hour TTL.

    Args:
        inp: Typed task input.
        ctx: Current node context (unused; present for signature compatibility).

    Returns:
        ``CrawlUrlOutput`` with ``from_cache=True`` on a hit, or ``None``.
    """
    cache_key = _make_cache_key(inp.url)
    async with raw_conn(readonly=True) as conn:
        cur = await conn.execute(InputRawSQL.GET_CACHED, (cache_key,))
        row = await cur.fetchone()
    if row is None:
        return None
    cached: dict = row["output"]
    return CrawlUrlOutput.model_validate({**cached, "from_cache": True})


crawl_url: NodeTask[CrawlUrlInput, CrawlUrlOutput] = NodeTask(
    name=_TASK_NAME,
    description=(
        "Fetch a web page by URL (http/https), follow redirects, "
        "extract hyperlinks from the HTML body, and return the raw HTML with metadata. "
        "Caches raw output in fin_markets.input_raw with a 4-hour TTL."
    ),
    input_type=CrawlUrlInput,
    output_type=CrawlUrlOutput,
    task_fn=_crawl_url_task,
    handler=_handler,
    pg_cache_fn=_crawl_url_pg_cache,
)

HANDLERS: dict = {_TASK_NAME: _handler}

__all__ = [
    "CrawlUrlInput",
    "CrawlUrlOutput",
    "crawl_url",
    "HANDLERS",
]
