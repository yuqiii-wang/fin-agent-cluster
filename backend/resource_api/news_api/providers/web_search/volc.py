"""Volcano Engine web-search backend.

Uses the Volcano Engine REST API with HMAC-SHA256 request signing
(analogous to AWS Signature Version 4).

Reference:
  https://www.volcengine.com/docs/6369/67269  (signing algorithm)

Required env vars:
  VOLCENGINE_ACCESS_KEY_ID      — Volcano Engine AK
  VOLCENGINE_SECRET_ACCESS_KEY  — Volcano Engine SK
  VOLC_SEARCH_HOST              — API host (default: open.volcengineapi.com)
  VOLC_SEARCH_SERVICE           — Service name registered in Volcano Engine
  VOLC_SEARCH_REGION            — Region (default: cn-north-1)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

from backend.config import get_settings
from backend.resource_api.news_api.models import NewsArticle, NewsQuery, NewsResult

logger = logging.getLogger(__name__)


def is_configured() -> bool:
    """Return True when Volcano Engine credentials are present."""
    s = get_settings()
    return bool(s.VOLCENGINE_ACCESS_KEY_ID and s.VOLCENGINE_SECRET_ACCESS_KEY)


# ---------------------------------------------------------------------------
# Volcano Engine HMAC-SHA256 signing (mirrors AWS SigV4)
# ---------------------------------------------------------------------------

def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _make_signing_key(secret_key: str, date_str: str, region: str, service: str) -> bytes:
    """Derive the signing key from the secret key and request context."""
    k_date = _hmac_sha256(("VOLC" + secret_key).encode("utf-8"), date_str)
    k_region = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    return _hmac_sha256(k_service, "request")


def _build_auth_headers(
    method: str,
    host: str,
    path: str,
    query_string: str,
    payload: bytes,
    access_key: str,
    secret_key: str,
    region: str,
    service: str,
) -> dict[str, str]:
    """Construct the Authorization and X-Date headers for a Volcano Engine request.

    Args:
        method:       HTTP method (uppercase).
        host:         Request host without scheme.
        path:         URL path.
        query_string: Pre-encoded query string.
        payload:      Raw request body bytes.
        access_key:   Volcano Engine Access Key ID.
        secret_key:   Volcano Engine Secret Access Key.
        region:       Service region.
        service:      Volcano Engine service identifier.

    Returns:
        Dict with ``X-Date`` and ``Authorization`` headers.
    """
    now = datetime.now(timezone.utc)
    date_time = now.strftime("%Y%m%dT%H%M%SZ")
    date_only = now.strftime("%Y%m%d")

    signed_headers = "content-type;host;x-content-sha256;x-date"
    content_sha256 = _sha256_hex(payload)
    content_type = "application/json"

    canonical_headers = (
        f"content-type:{content_type}\n"
        f"host:{host}\n"
        f"x-content-sha256:{content_sha256}\n"
        f"x-date:{date_time}\n"
    )

    canonical_request = "\n".join([
        method,
        path,
        query_string,
        canonical_headers,
        signed_headers,
        content_sha256,
    ])

    credential_scope = f"{date_only}/{region}/{service}/request"
    string_to_sign = "\n".join([
        "HMAC-SHA256",
        date_time,
        credential_scope,
        _sha256_hex(canonical_request.encode("utf-8")),
    ])

    signing_key = _make_signing_key(secret_key, date_only, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    authorization = (
        f"HMAC-SHA256 Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )

    return {
        "X-Date": date_time,
        "X-Content-Sha256": content_sha256,
        "Content-Type": content_type,
        "Authorization": authorization,
    }


# ---------------------------------------------------------------------------
# Fetch implementation
# ---------------------------------------------------------------------------

async def fetch(query: NewsQuery) -> NewsResult:
    """Fetch web search results via Volcano Engine signed API.

    The request body follows the Volcano Engine search service convention.
    Adjust ``VOLC_SEARCH_SERVICE`` and the request schema to match your
    specific Volcano Engine product (e.g. VeSearch, 智能搜索).

    Args:
        query: Structured news query.

    Returns:
        Normalised :class:`~app.resource_api.news_api.models.NewsResult`.

    Raises:
        ValueError: When credentials are not configured.
        httpx.HTTPStatusError: On non-2xx API responses.
    """
    s = get_settings()
    if not s.VOLCENGINE_ACCESS_KEY_ID or not s.VOLCENGINE_SECRET_ACCESS_KEY:
        raise ValueError("VOLCENGINE_ACCESS_KEY_ID and VOLCENGINE_SECRET_ACCESS_KEY must be configured")

    limit = int(query.params.get("limit", 20))

    if query.method == "company_news" and query.symbol:
        q_text = f"{query.symbol.upper()} stock news"
    elif query.method == "topic_news" and query.query:
        q_text = query.query
    else:
        raise ValueError("volc provider requires symbol (company_news) or query (topic_news)")

    host = s.VOLC_SEARCH_HOST
    region = s.VOLC_SEARCH_REGION
    service = s.VOLC_SEARCH_SERVICE
    method = "POST"
    path = "/"

    # Query params: Action and Version are standard Volcano Engine API params
    qs_params = {
        "Action": "SearchWebPages",
        "Version": "2023-01-01",
    }
    query_string = urlencode(sorted(qs_params.items()))

    body_dict = {"Query": q_text, "Count": limit}
    payload = json.dumps(body_dict, ensure_ascii=False).encode("utf-8")

    auth_headers = _build_auth_headers(
        method=method,
        host=host,
        path=path,
        query_string=query_string,
        payload=payload,
        access_key=s.VOLCENGINE_ACCESS_KEY_ID,
        secret_key=s.VOLCENGINE_SECRET_ACCESS_KEY,
        region=region,
        service=service,
    )

    url = f"https://{host}{path}?{query_string}"

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.request(method, url, content=payload, headers={**auth_headers, "Host": host})
        resp.raise_for_status()
        data = resp.json()

    # Normalise response — adapt field paths to match actual Volcano API response schema
    raw_items: list[dict] = (
        data.get("Result", {}).get("WebPages", {}).get("Value", [])
        or data.get("results", [])
        or []
    )
    logger.debug("[volc] query=%r returned %d results", q_text, len(raw_items))

    articles = []
    for item in raw_items:
        published_at: str | None = item.get("dateLastCrawled") or item.get("publishedAt")
        if published_at:
            try:
                dt = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
                published_at = dt.isoformat()
            except ValueError:
                pass

        articles.append(
            NewsArticle(
                title=item.get("name") or item.get("title", ""),
                url=item.get("url"),
                source_name=item.get("displayUrl") or item.get("source", "volcengine"),
                published_at=published_at,
                summary=item.get("snippet") or item.get("body"),
            )
        )

    return NewsResult(
        method=query.method,
        source="web_search",
        symbol=query.symbol,
        query=query.query,
        articles=articles,
        fetched_at=datetime.now(timezone.utc),
    )
