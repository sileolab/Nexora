"""Phase 3 Unit and Integration Tests:
Session Manager Connection Pooling, Tenant Cookie Isolation,
Domain Policy Overrides, Crawl-Delay Sync, and Pipeline Integration.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch
import httpx
import pytest

from app.schemas.documents import ExtractedDocument, QualityStatus
from app.services.anti_bot import (
    AntiBotManager,
    DomainPolicy,
    DomainPolicyManager,
    RequestDiagnostics,
    ResponseClassification,
    SessionManager,
    get_antibot_manager,
)
from app.services.crawler import CrawlerService
from app.services.extractor import ContentExtractor


# ==============================================================================
# 1. SessionManager Connection Pooling & Tenant Isolation Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_session_manager_connection_pooling():
    """Consecutive calls for the same tenant must return the exact same client instance."""
    sm = SessionManager()

    client1 = await sm.get_client("tenant-pool-1")
    client2 = await sm.get_client("tenant-pool-1")

    assert client1 is client2
    assert client1.is_closed is False

    await sm.close_all()
    assert client1.is_closed is True


@pytest.mark.asyncio
async def test_session_manager_tenant_isolation():
    """Different tenants must receive isolated client instances with zero cookie bleed."""
    sm = SessionManager()

    client_a = await sm.get_client("tenant-alpha")
    client_b = await sm.get_client("tenant-beta")

    assert client_a is not client_b

    # Set cookie in tenant A
    client_a.cookies.set("auth_session", "alpha_secret_token", domain="example.com")

    # Assert tenant B has no access to tenant A's cookies
    assert client_b.cookies.get("auth_session", domain="example.com") is None

    await sm.close_all()


@pytest.mark.asyncio
async def test_session_manager_close_client():
    """Closing a specific tenant client must close and evict it from registry."""
    sm = SessionManager()

    client_a = await sm.get_client("tenant-to-close")
    assert client_a.is_closed is False

    await sm.close_client("tenant-to-close")
    assert client_a.is_closed is True

    # Next call must create a new client
    client_new = await sm.get_client("tenant-to-close")
    assert client_new is not client_a
    assert client_new.is_closed is False

    await sm.close_all()


# ==============================================================================
# 2. Domain Policy Manager Tests
# ==============================================================================

def test_domain_policy_manager_custom_overrides():
    """DomainPolicyManager must resolve exact domain, subdomains, or default fallback."""
    pm = DomainPolicyManager(default_policy=DomainPolicy(domain="*", max_concurrency=2, min_delay_seconds=0.5))

    # Register custom policy for specific domain
    custom_policy = DomainPolicy(
        domain="api.myvendor.com",
        max_concurrency=5,
        min_delay_seconds=0.1,
        request_timeout=15.0,
    )
    pm.set_policy(custom_policy)

    # 1. Exact match
    matched = pm.get_policy("https://api.myvendor.com/v1/users")
    assert matched.max_concurrency == 5
    assert matched.min_delay_seconds == 0.1
    assert matched.request_timeout == 15.0

    # 2. Fallback to default
    default_matched = pm.get_policy("https://unknown-site.org/index")
    assert default_matched.max_concurrency == 2
    assert default_matched.min_delay_seconds == 0.5


def test_domain_policy_manager_set_crawl_delay():
    """set_crawl_delay must register or update domain delay dynamically from robots.txt."""
    pm = DomainPolicyManager()

    pm.set_crawl_delay("https://slowdomain.com/path", 3.0)
    policy = pm.get_policy("https://slowdomain.com/other")

    assert policy.min_delay_seconds == 3.0


# ==============================================================================
# 3. ContentExtractor Pipeline Integration Tests
# ==============================================================================

class MockExtractTransport(httpx.AsyncBaseTransport):
    """Transport for testing ContentExtractor with AntiBotManager."""

    def __init__(self, status_code: int = 200, text: str = "<html><body><h1>Page</h1><p>Sample content for extraction.</p></body></html>"):
        self.status_code = status_code
        self.text = text
        self.call_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        return httpx.Response(
            status_code=self.status_code,
            headers={"Content-Type": "text/html; charset=utf-8"},
            text=self.text,
            request=request,
        )


@pytest.mark.asyncio
async def test_content_extractor_uses_antibot_connection():
    """ContentExtractor must successfully fetch using AntiBotManager."""
    transport = MockExtractTransport(200, "<html><body><h1>Title</h1><p>" + ("Sentence text. " * 30) + "</p></body></html>")
    client = httpx.AsyncClient(transport=transport)

    extractor = ContentExtractor(strategy="trafilatura", client=client, tenant_id="tenant-extract-test")
    doc = await extractor.extract("https://example.com/item1")

    assert doc is not None
    assert doc.quality_status == QualityStatus.SUCCESS
    assert doc.http_status == 200
    assert transport.call_count == 1


@pytest.mark.asyncio
async def test_content_extractor_auto_promotes_on_js_render_required():
    """When AntiBotManager detects JS_RENDER_REQUIRED, ContentExtractor auto-promotes to browser."""
    # HTML with empty SPA container and negligible text -> classified as JS_RENDER_REQUIRED
    spa_html = "<html><head><title>SPA</title></head><body><div id='app'></div></body></html>"
    transport = MockExtractTransport(200, spa_html)
    client = httpx.AsyncClient(transport=transport)

    extractor = ContentExtractor(strategy="auto", client=client, render_mode="auto")

    # Mock the browser direct extraction method
    mock_browser_doc = ExtractedDocument(
        url="https://example.com/spa",
        extraction_method="crawl4ai",
        extractor_used="crawl4ai",
        quality_status=QualityStatus.SUCCESS,
        content_text="Rendered content from headless browser",
    )

    with patch.object(extractor, "_extract_via_crawl4ai_direct", new_callable=AsyncMock, return_value=mock_browser_doc) as mock_b:
        res = await extractor.extract("https://example.com/spa")

        assert mock_b.called, "Browser fallback should be invoked when JS_RENDER_REQUIRED is detected"
        assert res.extractor_used == "crawl4ai"


# ==============================================================================
# 4. CrawlerService Integration & Crawl-Delay Sync
# ==============================================================================

@pytest.mark.asyncio
async def test_crawler_service_syncs_crawl_delay_to_domain_policy():
    """CrawlerService must register robots.txt crawl-delay into DomainPolicyManager."""
    antibot = get_antibot_manager()
    crawler = CrawlerService(root_url="https://crawl-delay-domain.com", tenant_id="tenant-crawl")

    # Mock robots.txt returning Crawl-delay: 2.5
    with patch.object(crawler.robots_checker, "fetch_robots", new_callable=AsyncMock), \
         patch.object(crawler.robots_checker, "get_crawl_delay", return_value=2.5), \
         patch.object(crawler.robots_checker, "is_allowed", return_value=True), \
         patch.object(crawler, "_discover_sitemaps", new_callable=AsyncMock), \
         patch.object(crawler, "_crawl_bfs", new_callable=AsyncMock):

        mock_client = httpx.AsyncClient(transport=MockExtractTransport(200))
        await crawler._run_crawl_pipeline(mock_client, "https://crawl-delay-domain.com")

        assert crawler.delay == 2.5
        policy = antibot.policy_manager.get_policy("crawl-delay-domain.com")
        assert policy.min_delay_seconds >= 2.5
