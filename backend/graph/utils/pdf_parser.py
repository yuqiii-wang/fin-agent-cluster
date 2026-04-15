"""PDF download and text-extraction utility.

Used by the market-data news tasks to read financial reports (10-K, 10-Q,
annual reports, etc.) that are published as PDF files.

Requires ``pypdf`` (install via ``pip install pypdf``) and ``httpx``
(already a project dependency).  Both imports are guarded — a missing
``pypdf`` installation produces a ``None`` result rather than an exception.
"""

from __future__ import annotations

import logging
from io import BytesIO
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# Domains/path fragments that strongly suggest a PDF is a financial filing.
_PDF_URL_SIGNALS = (
    ".pdf",
    "/sec.gov/",
    "edgar.sec.gov",
    "/annual-report",
    "/annual_report",
    "/form-10-k",
    "/form-10k",
    "/form-20-f",
    "/investor-relations",
    "/ir/",
    "/reports/",
    "/filings/",
)

_MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024  # 20 MB safety cap
_DEFAULT_MAX_PAGES = 25


def is_pdf_url(url: str) -> bool:
    """Return ``True`` if the URL likely points to a PDF financial document.

    Args:
        url: Candidate URL string.

    Returns:
        ``True`` when the URL ends with ``.pdf`` or contains known IR/filing path fragments.
    """
    lower = url.lower()
    return any(signal in lower for signal in _PDF_URL_SIGNALS)


def _extract_text_pypdf(data: bytes, max_pages: int) -> str:
    """Extract text from PDF bytes using ``pypdf``.

    Args:
        data:      Raw PDF bytes.
        max_pages: Maximum number of pages to read.

    Returns:
        Extracted text string (may be empty if the PDF is image-only).
    """
    try:
        import pypdf  # noqa: PLC0415 — optional dependency
    except ImportError:
        logger.warning("[pdf_parser] pypdf is not installed — run `pip install pypdf`")
        return ""

    reader = pypdf.PdfReader(BytesIO(data))
    pages = reader.pages[:max_pages]
    parts: list[str] = []
    for page in pages:
        try:
            text = page.extract_text() or ""
            if text.strip():
                parts.append(text)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[pdf_parser] page extraction error: %s", exc)
    return "\n".join(parts)


async def fetch_and_parse_pdf(
    url: str,
    max_pages: int = _DEFAULT_MAX_PAGES,
    timeout_seconds: float = 30.0,
) -> Optional[str]:
    """Download a PDF from ``url`` and return extracted plain text.

    Args:
        url:             Public URL of the PDF document.
        max_pages:       Maximum number of pages to extract (default 25).
        timeout_seconds: HTTP request timeout in seconds (default 30).

    Returns:
        Extracted text string, or ``None`` if download or parsing fails.
    """
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0 (financial-research-agent/1.0)"},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()

            content_type = response.headers.get("content-type", "")
            if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
                logger.debug(
                    "[pdf_parser] URL %s content-type=%s — not treating as PDF", url, content_type
                )
                return None

            raw_bytes = response.content
            if len(raw_bytes) > _MAX_DOWNLOAD_BYTES:
                logger.warning(
                    "[pdf_parser] PDF at %s is %.1f MB — truncating to %d MB",
                    url,
                    len(raw_bytes) / (1024 * 1024),
                    _MAX_DOWNLOAD_BYTES // (1024 * 1024),
                )
                raw_bytes = raw_bytes[:_MAX_DOWNLOAD_BYTES]

        text = _extract_text_pypdf(raw_bytes, max_pages)
        if not text.strip():
            logger.info("[pdf_parser] PDF at %s parsed but yielded no extractable text", url)
            return None

        logger.info(
            "[pdf_parser] extracted %d chars from PDF at %s (pages capped at %d)",
            len(text),
            url,
            max_pages,
        )
        return text

    except httpx.HTTPStatusError as exc:
        logger.warning("[pdf_parser] HTTP %s fetching %s: %s", exc.response.status_code, url, exc)
    except httpx.RequestError as exc:
        logger.warning("[pdf_parser] request error fetching %s: %s", url, exc)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[pdf_parser] unexpected error parsing PDF at %s: %s", url, exc)
    return None
