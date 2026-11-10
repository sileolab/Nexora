"""Unit and Integration Tests for Phase 4:
Robots.txt, Sitemap Discovery, and Browser Rendering Integration with Security Boundaries.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
import httpx

from app.schemas.documents import ExtractedDocument, QualityStatus
from app.services.anti_bot import (
    ResponseClassification,
    RequestDiagnostics,
    get_antibot_manager,
)
from app.services.crawler import CrawlerService
from app.services.extractor import ContentExtractor
from app.services.extractors.base import EngineResult
from app.services.extractors.playwright_engine import (
    PlaywrightEngine,
    BrowserConcurrencyLimiter,
)
from app.services.robots_parser import (
    RobotsChecker,
    RobotsFetchStatus,
    RobotsDecision,
)
from app.services.sitemap_discovery import SitemapParser


# ==============================================================================
# 1. Robots.txt: Detailed RFC 9309 Decisions & Configurable Failure Policies
# ==============================================================================

@pytest.mark.asyncio
async def test_robots_distinguishes_rules_vs_missing():
    """Verify distinction between explicit Disallow rule and 404 missing robots.txt."""
    checker = RobotsChecker(failure_policy="lenient")

    # Domain A: 200 OK with explicit rules
    robots_content = "User-agent: *\nDisallow: /secret/\nAllow: /public/\n"
    def handler_a(request):
        return httpx.Response(200, text=robots_content)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_a)) as client:
        await checker.fetch_robots("https://domain-a.com", client)

    dec_allow = checker.can_fetch_detailed("https://domain-a.com/public/doc")
    assert dec_allow.allowed is True
    assert dec_allow.status == RobotsFetchStatus.FETCHED_SUCCESS
    assert "explicit_allow" in dec_allow.reason

    dec_disallow = checker.can_fetch_detailed("https://domain-a.com/secret/key")
    assert dec_disallow.allowed is False
    assert dec_disallow.status == RobotsFetchStatus.FETCHED_SUCCESS
    assert "explicit_disallow" in dec_disallow.reason

    # Domain B: 404 Not Found (RFC 9309 allows unrestricted crawl)
    def handler_b(request):
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_b)) as client:
        await checker.fetch_robots("https://domain-b.com", client)

    dec_404 = checker.can_fetch_detailed("https://domain-b.com/anything")
    assert dec_404.allowed is True
    assert dec_404.status == RobotsFetchStatus.NOT_FOUND
    assert "robots_not_found" in dec_404.reason


@pytest.mark.asyncio
async def test_robots_strict_policy_on_access_denied_and_server_error():
    """Verify that strict failure_policy disallows crawl when robots.txt is forbidden or 500."""
    strict_checker = RobotsChecker(failure_policy="strict")

    # 403 Forbidden robots.txt
    def handler_403(request):
        return httpx.Response(403)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_403)) as client:
        await strict_checker.fetch_robots("https://forbidden-site.org", client)

    dec_403 = strict_checker.can_fetch_detailed("https://forbidden-site.org/page")
    assert dec_403.allowed is False
    assert dec_403.status == RobotsFetchStatus.ACCESS_DENIED
    assert "robots_access_denied" in dec_403.reason

    # 500 Server Error robots.txt (RFC 9309 section 2.3.1.3 should suspend)
    def handler_500(request):
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler_500)) as client:
        await strict_checker.fetch_robots("https://server-err.org", client)

    dec_500 = strict_checker.can_fetch_detailed("https://server-err.org/page")
    assert dec_500.allowed is False
    assert dec_500.status == RobotsFetchStatus.SERVER_ERROR
    assert "robots_server_error" in dec_500.reason


# ==============================================================================
# 2. Sitemap Discovery: Independent Error Management & Cache
# ==============================================================================

@pytest.mark.asyncio
async def test_sitemap_discovery_handles_403_independently():
    """Verify that a 403 Forbidden on /sitemap.xml is handled gracefully without crashing."""
    def handler(request):
        if "/sitemap.xml" in str(request.url):
            return httpx.Response(403)
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        parser = SitemapParser(client, max_urls=100)
        urls = await parser.try_default_sitemaps("https://example.com")
        assert urls == []

        diag = parser.get_diagnostics()
        assert diag["failed_sitemaps"] >= 1
        assert any(d.get("status") == 403 for d in diag["details"])


@pytest.mark.asyncio
async def test_sitemap_discovery_prevents_repeated_failed_requests():
    """Verify that failed/broken sitemap URLs are cached and not re-requested."""
    request_count = 0
    def handler(request):
        nonlocal request_count
        request_count += 1
        return httpx.Response(500)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        parser = SitemapParser(client, max_urls=100)
        await parser.parse_sitemap("https://example.com/broken.xml")
        assert request_count == 1

        # Second call to same URL should hit cache and not make another HTTP request
        await parser.parse_sitemap("https://example.com/broken.xml")
        assert request_count == 1


# ==============================================================================
# 3. Browser Rendering: Security Boundary on Bot / Captcha / 403 Bypass
# ==============================================================================

@pytest.mark.asyncio
async def test_browser_fallback_strictly_prohibited_on_bot_protection():
    """Verify that when HTTP fetch indicates BOT_PROTECTION, browser fallback is NOT attempted."""
    extractor = ContentExtractor(strategy="auto")

    # Mock response diagnostics indicating Bot Protection (e.g. Cloudflare Turnstile / Challenge)
    diag = RequestDiagnostics(
        url="https://protected.com",
        domain="protected.com",
        http_status=403,
        classification=ResponseClassification.BOT_PROTECTION,
        retryable=False,
        suggested_action="terminate",
        reason="Cloudflare security challenge detected",
        execution_time_ms=120.0,
        attempt_count=1,
    )

    fetch_res = {
        "failed": True,
        "error": "Cloudflare security challenge detected",
        "final_url": "https://protected.com",
        "status_code": 403,
        "diagnostics": diag,
    }

    with patch.object(extractor, "_safe_fetch_html", return_value=fetch_res), \
         patch.object(extractor.playwright_engine, "extract") as mock_pw, \
         patch.object(extractor.crawl4ai_engine, "extract") as mock_c4a:

        doc = await extractor.extract("https://protected.com")

        # Must NOT call browser engines to bypass bot challenges
        mock_pw.assert_not_called()
        mock_c4a.assert_not_called()

        assert doc.quality_status == QualityStatus.BLOCKED
        assert "BOT_PROTECTION" in doc.warnings[0]


@pytest.mark.asyncio
async def test_browser_fallback_strictly_prohibited_on_captcha():
    """Verify that when HTTP fetch indicates CAPTCHA_REQUIRED, browser fallback is NOT attempted."""
    extractor = ContentExtractor(strategy="auto")

    diag = RequestDiagnostics(
        url="https://captcha.com",
        domain="captcha.com",
        http_status=403,
        classification=ResponseClassification.CAPTCHA_REQUIRED,
        retryable=False,
        suggested_action="terminate",
        reason="reCAPTCHA challenge required",
        execution_time_ms=115.0,
        attempt_count=1,
    )

    fetch_res = {
        "failed": True,
        "error": "reCAPTCHA challenge required",
        "final_url": "https://captcha.com",
        "status_code": 403,
        "diagnostics": diag,
    }

    with patch.object(extractor, "_safe_fetch_html", return_value=fetch_res), \
         patch.object(extractor.playwright_engine, "extract") as mock_pw:

        doc = await extractor.extract("https://captcha.com")

        mock_pw.assert_not_called()
        assert doc.quality_status == QualityStatus.BLOCKED
        assert "CAPTCHA_REQUIRED" in doc.warnings[0]


@pytest.mark.asyncio
async def test_browser_fallback_permitted_on_js_render_required():
    """Verify that when HTTP fetch indicates JS_RENDER_REQUIRED, browser fallback IS attempted."""
    extractor = ContentExtractor(strategy="auto")

    diag = RequestDiagnostics(
        url="https://spa-app.com",
        domain="spa-app.com",
        http_status=200,
        classification=ResponseClassification.JS_RENDER_REQUIRED,
        retryable=False,
        suggested_action="render_js",
        reason="Client-side SPA shell without static content",
        execution_time_ms=85.0,
        attempt_count=1,
    )

    fetch_res = {
        "failed": False,
        "html": "<div id='root'></div><script src='app.js'></script>",
        "final_url": "https://spa-app.com",
        "status_code": 200,
        "diagnostics": diag,
    }

    mock_c4a_result = EngineResult(
        engine="crawl4ai",
        success=True,
        text="محتوای کامل برنامه تک صفحه‌ای استخراج شد. " * 8,
        markdown="# عنوان SPA\n\nمتن استخراج شده.",
        title="داشبورد SPA",
        char_count=400,
        word_count=60,
    )

    with patch.object(extractor, "_safe_fetch_html", return_value=fetch_res), \
         patch.object(extractor.crawl4ai_engine, "extract", new=AsyncMock(return_value=mock_c4a_result)):

        doc = await extractor.extract("https://spa-app.com")
        assert doc.quality_status == QualityStatus.SUCCESS
        assert doc.extractor_used == "crawl4ai"
        assert "محتوای کامل برنامه تک صفحه‌ای" in (doc.content_text or "")


# ==============================================================================
# 4. Browser Concurrency Limiter
# ==============================================================================

@pytest.mark.asyncio
async def test_browser_concurrency_limiter():
    """Verify that BrowserConcurrencyLimiter coordinates simultaneous browser tasks."""
    BrowserConcurrencyLimiter.set_max_concurrency(2)
    sem = BrowserConcurrencyLimiter.get_semaphore()

    active_count = 0
    max_observed = 0

    async def simulate_browser_task():
        nonlocal active_count, max_observed
        async with sem:
            active_count += 1
            if active_count > max_observed:
                max_observed = active_count
            await asyncio.sleep(0.05)
            active_count -= 1

    tasks = [asyncio.create_task(simulate_browser_task()) for _ in range(6)]
    await asyncio.gather(*tasks)

    assert max_observed <= 2
    # Restore default
    BrowserConcurrencyLimiter.set_max_concurrency(2)
