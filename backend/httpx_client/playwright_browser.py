"""playwright_browser — headless browser interaction utilities.

Provides async helpers that use Playwright to navigate to a URL, perform
interactive DOM actions (e.g. clicking a cookie-consent button), and return
the resulting HTML after the interaction.

Unlike :mod:`httpx_client.factory`, these helpers operate at the rendered-DOM
level — JavaScript executes, consent dialogs appear, and interactive elements
can be manipulated.

Design notes
------------
* A fresh browser context is created per call so cookies/state cannot bleed
  between unrelated pipeline tasks.
* Proxy is read from ``settings.HTTP_PROXY`` when set.
* The helper is intentionally synchronous-friendly: ``click_and_get_html`` is
  an async coroutine suitable for direct ``await`` in Celery async tasks or
  wrapped in ``asyncio.run`` from sync workers.

Public exports
--------------
``click_and_get_html``     — Navigate, click a locator, return final HTML.
"""

from __future__ import annotations

import logging

from backend.config import get_settings

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_MS: int = 15_000
"""Default Playwright action / navigation timeout in milliseconds."""

_POST_CLICK_TIMEOUT_MS: int = 10_000
"""Timeout (ms) to wait for a post-click navigation / network-idle to settle."""


async def click_and_get_html(
    url: str,
    locator: str,
    timeout_ms: int = _DEFAULT_TIMEOUT_MS,
) -> str:
    """Navigate to *url* in headless Chromium, click *locator*, return final HTML.

    Opens a headless Playwright Chromium browser, navigates to *url*, waits
    for the DOM to reach ``networkidle``, then attempts to click the element
    matched by *locator*.  After the click the outer HTML of ``<html>`` is
    returned so callers can feed it through :func:`html_to_markdown` for a
    clean Markdown representation of the page without the overlay.

    If *locator* matches no element (e.g. the pop-up already closed or the
    selector was wrong) the page HTML is returned as-is — the caller should
    treat this as a best-effort result.

    Args:
        url:        HTTP/HTTPS URL to navigate to.
        locator:    Playwright-compatible locator string, e.g.
                    ``"button:has-text('Accept All')"`` or ``"#cookie-accept"``.
        timeout_ms: Maximum time (ms) for navigation and element actions.
                    Defaults to 15 000 ms.

    Returns:
        Outer HTML string of the full page after the interaction.

    Raises:
        RuntimeError: Playwright import failed (library not installed) or the
                      browser process could not start.
    """
    try:
        from playwright.async_api import async_playwright  # type: ignore[import]
    except ImportError as exc:
        raise RuntimeError(
            "playwright is not installed — run: pip install playwright && playwright install chromium"
        ) from exc

    settings = get_settings()

    proxy_settings: dict | None = None
    if settings.HTTP_PROXY:
        proxy_settings = {"server": settings.HTTP_PROXY}

    async with async_playwright() as pw:
        launch_args: list[str] = []
        if settings.PLAYWRIGHT_NO_SANDBOX:
            # Required in WSL2 / Docker / root environments where Chrome's
            # sandbox is not available.
            launch_args.extend(["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])

        launch_kwargs: dict = {
            "headless": True,
            "args": launch_args,
        }
        if proxy_settings:
            launch_kwargs["proxy"] = proxy_settings
        if settings.PLAYWRIGHT_CHROMIUM_PATH:
            launch_kwargs["executable_path"] = settings.PLAYWRIGHT_CHROMIUM_PATH

        browser = await pw.chromium.launch(**launch_kwargs)
        try:
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                ignore_https_errors=True,
            )
            page = await context.new_page()
            page.set_default_timeout(timeout_ms)

            await page.goto(url, wait_until="networkidle", timeout=timeout_ms)

            # Attempt to click the close/accept element; tolerate selector misses.
            element = page.locator(locator).first
            try:
                # Wait for any navigation triggered by the click (e.g. Yahoo
                # consent → actual finance page) then wait for network idle.
                async with page.expect_navigation(
                    wait_until="networkidle", timeout=_POST_CLICK_TIMEOUT_MS
                ):
                    await element.click(timeout=timeout_ms)
            except Exception as click_exc:
                logger.error(
                    "playwright_browser: locator %r not found / click/navigation failed for url=%r: %s",
                    locator,
                    url,
                    click_exc,
                )

            html: str = await page.content()
        finally:
            await browser.close()

    return html


__all__ = ["click_and_get_html"]
