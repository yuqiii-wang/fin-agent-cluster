"""ARK web-search and AI-summary async client (Responses API).

Wraps Volcano Engine / Doubao's ``/api/v3/responses`` endpoint with the
``web_search`` tool.  This is the "官方" (documented) pattern for
invoking the Doubao 联网内容插件 from outside the platform; see
``volcengine.com/docs/82379/1338552`` for the schema.

Responses vs. Chat Completions
------------------------------------
The Responses API is preferred for this provider because it natively
understands ``tools=[{"type":"web_search"}]`` and returns both a
textual summary (``output_text``) together with provider-defined
``tool_use`` artifacts that carry the matched citations.  The older
``/chat/completions`` endpoint only returns ``tool_calls`` for
function-calling models and is not the documented path for the web
search plugin.

Response normalisation
----------------------
The raw Doubao ``responses`` payload (simplified)::

    {
      "id": "...",
      "model": "doubao-seed-1-6-250615",
      "output": [
        {
          "type": "message",
          "role": "assistant",
          "content": [
            {"type": "text", "text": "摘要文本..."},
            {
              "type": "tool_use",
              "id": "...",
              "name": "web_search",
              "input": { ... raw search hits ... }
            }
          ]
        }
      ],
      "usage": {"input_tokens": 12, "output_tokens": 34, ...}
    }

:meth:`ArkWebSearchClient.search_and_summary` extracts the text
answer from the first ``type="text"`` content item and the list of
citation records from the first ``type="tool_use"`` item with
``name="web_search"``.  Results are normalised to
:class:`ArkSearchSummaryResponse`.

Typical usage::

    from backend.resources.web_knowledge.providers.ark import ArkWebSearchClient

    client = ArkWebSearchClient()
    resp = await client.search_and_summary("苹果公司最新财报要点")
    print(resp.answer)
    for r in resp.results:
        print(r.title, r.url)
    await client.aclose()

Configuration (loaded from ``.env`` via :mod:`backend.config`):

* ``ARK_SEARCH_API_KEY``  — API key with the 联网搜索 capability.
  When blank the provider falls back to ``ARK_API_KEY`` so a single
  key works for simple deployments.
* ``ARK_SEARCH_BASE_URL`` — default ``https://ark.cn-beijing.volces.com/api/v3``.
* ``ARK_SEARCH_MODEL``    — the model / endpoint ID passed in the
  ``model`` field (``doubao-seed-1-6-250615`` or your ``ep-xxx``
  reasoning access point).
* ``ARK_SEARCH_TIMEOUT_SECONDS`` — per-request HTTP timeout.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from backend.config import get_settings
from backend.resources.web_knowledge.providers.ark.errors import (
    ARK_CONNECT_ERROR,
    ARK_EMPTY_QUERY,
    ARK_HTTP_ERROR,
    ARK_MALFORMED_RESPONSE,
    ARK_MISSING_CREDENTIALS,
    ARK_TIMEOUT,
    ARK_WEB_SEARCH_UNSUPPORTED,
)
from backend.resources.web_knowledge.providers.ark.models import (
    ArkSearchSummaryResponse,
    ArkWebSearchResult,
)
from _shared.httpx_client import ConnectError, TimeoutException, make_ark_async_client

logger = logging.getLogger(__name__)

#: Field-ordering preference when extracting strings from the raw
#: Doubao web-search citation objects.  The exact schema varies across
#: models; the helpers below pick the first non-empty match.
_TITLE_KEYS: tuple[str, ...] = ("title", "name", "headline", "source")
_URL_KEYS: tuple[str, ...] = ("url", "link", "href", "web_url")
_SNIPPET_KEYS: tuple[str, ...] = ("snippet", "content", "summary", "description", "body")
_DATE_KEYS: tuple[str, ...] = ("published_at", "date", "published", "timestamp", "time")
_CATEGORY_KEYS: tuple[str, ...] = ("category", "type", "vertical")


# ---------------------------------------------------------------------------
# Helpers -- parse Doubao responses independent of schema variant
# ---------------------------------------------------------------------------


def _pick_str(data: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
    return ""


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    if not value:
        return None
    formats = (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
        except ValueError:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    return None


def _normalise_hit(record: Any) -> ArkWebSearchResult | None:
    """Turn a raw Doubao search-hit dict into a structured :class:`ArkWebSearchResult`."""
    if record is None:
        return None
    if isinstance(record, str):
        return ArkWebSearchResult(title="", url="", snippet=record)
    if isinstance(record, list):
        for item in record:
            hit = _normalise_hit(item)
            if hit is not None and (hit.url or hit.title or hit.snippet):
                return hit
        return None
    if not isinstance(record, dict):
        return None

    title = _pick_str(record, _TITLE_KEYS)
    url = _pick_str(record, _URL_KEYS)
    snippet = _pick_str(record, _SNIPPET_KEYS)
    category = _pick_str(record, _CATEGORY_KEYS) or None
    date = _parse_date(_pick_str(record, _DATE_KEYS))

    if not title and not url and not snippet:
        return None
    return ArkWebSearchResult(
        title=title,
        url=url,
        snippet=snippet,
        source_category=category,
        published_at=date,
        raw=record,
    )


def _iter_hits(container: Any) -> list[Any]:
    """Flatten a Doubao ``tool_use.input`` or ``web_search_results`` container.

    The ``web_search`` tool input varies by model: sometimes it is a
    dict of ``{"results":[...]}``; sometimes it is already a list of
    hits; sometimes each hit is itself nested in ``{"result":{...}}``
    or ``{"hits":[...]}``.  This helper walks through each known
    shape and yields every flat dict record we can find.
    """
    out: list[Any] = []

    if container is None:
        return out

    if isinstance(container, list):
        for item in container:
            out.extend(_iter_hits(item))
        return out

    if isinstance(container, dict):
        found_nested = False
        for key in ("results", "items", "hits", "list", "data", "output"):
            value = container.get(key)
            if isinstance(value, list) and value:
                out.extend(_iter_hits(value))
                found_nested = True
        if not found_nested:
            # Treat the dict itself as a single citation record.
            out.append(container)
        return out

    # Strings / scalars: wrap them as snippet-only records.
    out.append({"snippet": str(container)})
    return out


def _extract_responses_payload(payload: dict[str, Any]) -> tuple[str, list[ArkWebSearchResult]]:
    """Extract ``(answer, citations)`` from the Doubao /responses body."""
    output = payload.get("output") or []
    answer_parts: list[str] = []
    hits_raw: list[Any] = []

    # Also look at ``payload.web_search_results`` and friends in case
    # Doubao returns a convenience top-level field.
    for key in ("web_search_results", "citations", "sources", "results"):
        if key in payload and isinstance(payload[key], list):
            hits_raw.extend(payload[key])

    for item in output:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text:
                answer_parts.append(text)
            continue
        if item.get("type") == "tool_use":
            tool_name = item.get("name") or item.get("tool_name") or ""
            if tool_name == "web_search":
                tool_input = item.get("input")
                if tool_input is not None:
                    hits_raw.extend(_iter_hits(tool_input))
            continue
        # Fallback: generic "message" style object with content list.
        content = item.get("content")
        if isinstance(content, list):
            for sub in content:
                if not isinstance(sub, dict):
                    continue
                if sub.get("type") == "text":
                    text = sub.get("text")
                    if isinstance(text, str) and text:
                        answer_parts.append(text)
                elif sub.get("type") == "tool_use":
                    tool_name = sub.get("name") or ""
                    if tool_name == "web_search":
                        tool_input = sub.get("input")
                        if tool_input is not None:
                            hits_raw.extend(_iter_hits(tool_input))
        elif isinstance(content, str) and content:
            answer_parts.append(content)

    # Deduplicate by URL (or title when URL missing) for a tidy summary.
    seen_urls: set[str] = set()
    citations: list[ArkWebSearchResult] = []
    for raw in hits_raw:
        hit = _normalise_hit(raw)
        if hit is None:
            continue
        key = hit.url or hit.title
        if key and key in seen_urls:
            continue
        if key:
            seen_urls.add(key)
        citations.append(hit)

    answer = "\n\n".join(answer_parts).strip()
    return answer, citations


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class ArkWebSearchClient:
    """Async client wrapping the Doubao ``/api/v3/responses`` endpoint with ``web_search``."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        """Create a client using :mod:`backend.config` when a parameter is ``None``.

        Args:
            api_key:         API key with web-search permission.  When unset
                             ``ARK_SEARCH_API_KEY`` is tried first then
                             ``ARK_API_KEY``.
            base_url:        Doubao base URL.  Defaults to
                             ``ARK_SEARCH_BASE_URL`` then ``ARK_BASE_URL``.
            model:           Model/endpoint ID passed as ``model`` in the
                             request body.  Defaults to ``ARK_SEARCH_MODEL``
                             then ``ARK_MODEL``.
            timeout_seconds: Per-request HTTP timeout.  Defaults to
                             ``ARK_SEARCH_TIMEOUT_SECONDS`` (60s).
        """
        settings = get_settings()

        self.api_key: str = (
            api_key
            or (getattr(settings, "ARK_SEARCH_API_KEY", None) if settings else None)
            or (getattr(settings, "ARK_API_KEY", None) if settings else None)
            or ""
        )
        # ``ARK_SEARCH_API_URL`` (full endpoint URL) takes priority over
        # ``ARK_SEARCH_BASE_URL`` (base URL — ``/responses`` is appended).
        search_api_url = getattr(settings, "ARK_SEARCH_API_URL", None) if settings else None
        self.base_url: str = (
            base_url
            or (getattr(settings, "ARK_SEARCH_BASE_URL", None) if settings else None)
            or (getattr(settings, "ARK_BASE_URL", None) if settings else None)
            or "https://ark.cn-beijing.volces.com/api/v3"
        )
        self.endpoint_url: str | None = (
            search_api_url.rstrip("/") if search_api_url else None
        )
        self.model: str = (
            model
            or (getattr(settings, "ARK_SEARCH_MODEL", None) if settings else None)
            or (getattr(settings, "ARK_MODEL", None) if settings else None)
            or "doubao-seed-1-6-250615"
        )
        # Resolve the timeout after we know what ``settings`` says.
        configured_timeout: float = float(
            getattr(settings, "ARK_SEARCH_TIMEOUT_SECONDS", 60) if settings else 60
        )
        self.timeout_seconds: float = configured_timeout if timeout_seconds is None else timeout_seconds

        # Trim trailing slashes so URL composition below is idempotent.
        self.base_url = self.base_url.rstrip("/")
        self._http = make_ark_async_client(timeout_seconds=self.timeout_seconds)

    async def search_and_summary(
        self,
        query: str,
        *,
        system_prompt: str | None = None,
        model: str | None = None,
        max_citations: int = 20,
    ) -> ArkSearchSummaryResponse:
        """Run a Doubao web-search + summary call.

        Args:
            query:          Free-form query (any language).  Must be non-empty.
            system_prompt:  Optional override for the assistant system prompt.
                            The default instructs Doubao to produce concise
                            Chinese-language summaries with inline citations.
            model:          Model/endpoint override (takes priority over
                            ``self.model``).
            max_citations:  Hard cap on the number of citation records kept in
                            the returned :class:`ArkSearchSummaryResponse`.

        Returns:
            :class:`ArkSearchSummaryResponse` with the textual answer and
            normalised citations.

        Raises:
            ValueError: For misconfiguration, empty query, or non-2xx HTTP
                        responses.  Messages are prefixed with ``[CODE]`` using
                        one of the constants from
                        :mod:`backend.resources.web_knowledge.providers.ark.errors`.
        """
        if not self.api_key:
            raise ValueError(
                f"[{ARK_MISSING_CREDENTIALS}] ARK web-search credentials are not configured. "
                "Set ARK_SEARCH_API_KEY (or ARK_API_KEY) in .env."
            )
        if not query or not query.strip():
            raise ValueError(f"[{ARK_EMPTY_QUERY}] search query is empty or whitespace only.")

        url = self.endpoint_url or f"{self.base_url}/responses"
        resolved_model = model or self.model
        request_body: dict[str, Any] = {
            "model": resolved_model,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": query,
                        }
                    ],
                }
            ],
            "tools": [{"type": "web_search"}],
            "stream": False,
        }
        if system_prompt:
            request_body["instruction"] = system_prompt

        headers = {"Authorization": f"Bearer {self.api_key}"}

        logger.info(
            "[ArkWebSearchClient] POST %s model=%s query_len=%d",
            url,
            resolved_model,
            len(query),
        )

        try:
            response = await self._http.post(url, json=request_body, headers=headers)
        except TimeoutException as exc:
            logger.error("[ArkWebSearchClient] timeout calling %s: %s", url, exc)
            raise ValueError(
                f"[{ARK_TIMEOUT}] ARK web-search request timed out after {self.timeout_seconds}s: {exc}"
            ) from exc
        except ConnectError as exc:
            logger.error("[ArkWebSearchClient] cannot connect to %s: %s", url, exc)
            raise ValueError(
                f"[{ARK_CONNECT_ERROR}] cannot reach ARK endpoint {url}: {exc}"
            ) from exc

        if response.status_code in (400, 403, 404):
            logger.error(
                "[ArkWebSearchClient] HTTP %s from %s — web_search unsupported; body=%.300s",
                response.status_code,
                url,
                response.text,
            )
            raise ValueError(
                f"[{ARK_WEB_SEARCH_UNSUPPORTED}] ARK HTTP {response.status_code} — model "
                f"'{resolved_model}' may not support the web_search tool or the API key "
                "lacks permission."
            )
        if response.status_code >= 400:
            logger.error(
                "[ArkWebSearchClient] HTTP %s from %s — body=%.500s",
                response.status_code,
                url,
                response.text,
            )
            raise ValueError(
                f"[{ARK_HTTP_ERROR}] ARK endpoint returned HTTP {response.status_code}."
            )

        try:
            data: dict[str, Any] = response.json()
        except ValueError as exc:
            logger.error(
                "[ArkWebSearchClient] non-JSON response from %s: %.200s", url, response.text
            )
            raise ValueError(
                f"[{ARK_MALFORMED_RESPONSE}] ARK response is not valid JSON: {exc}"
            ) from exc

        if not isinstance(data, dict):
            raise ValueError(
                f"[{ARK_MALFORMED_RESPONSE}] ARK response payload is not a JSON object."
            )

        answer, citations = _extract_responses_payload(data)

        if max_citations and len(citations) > max_citations:
            citations = citations[:max_citations]

        if not answer and not citations:
            logger.warning(
                "[ArkWebSearchClient] Doubao returned neither an answer nor citations "
                "for query=%.200r — the model may not support the web_search tool.",
                query,
            )

        return ArkSearchSummaryResponse(
            answer=answer,
            results=citations,
            provider="ark",
            raw={"response": data, "request": {"model": resolved_model, "endpoint": url}},
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()


__all__ = ["ArkWebSearchClient"]
