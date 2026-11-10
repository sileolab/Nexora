"""Comprehensive Multi-Algorithm URL Discovery & Resilience Tests.

Verifies end-to-end traversal across diverse web architectures:
1. Commercial WAF compatibility (exo.ir simulation: browser UA, modern headers)
2. Next.js SPA route extraction (__NEXT_DATA__ JSON hydration payloads)
3. Schema.org JSON-LD breadcrumb and item list discovery
4. HTML5 interactive elements (data-href, data-url, area, canonical, alternate)
5. Autonomous Playwright browser fallback on HTTP 403 / Bot Protection
6. Autonomous Playwright browser fallback on SPA loading screen shells
7. Persian / Unicode path normalization and deduplication
8. Nested XML sitemap index traversal
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.crawler import CrawlerService, DiscoveryResult, FetchResult
from app.services.extractors.base import EngineResult
from app.services.link_discovery import LinkDiscovery
from app.services.robots_parser import RobotsChecker
from app.services.sitemap_discovery import SitemapParser
from app.services.url_normalizer import URLNormalizer


# ==============================================================================
# 1. Tests for Multi-Algorithm LinkDiscovery (SPAs, JSON-LD, Attributes)
# ==============================================================================

class TestLinkDiscoveryMultiAlgorithm:
    """Verifies that LinkDiscovery extracts URLs from diverse DOM and script structures."""

    @pytest.fixture
    def normalizer(self) -> URLNormalizer:
        return URLNormalizer(allowed_domains=["example.com"])

    @pytest.fixture
    def discovery(self, normalizer: URLNormalizer) -> LinkDiscovery:
        return LinkDiscovery(normalizer)

    def test_extract_from_next_data_json(self, discovery: LinkDiscovery) -> None:
        """Extracts internal links embedded in Next.js __NEXT_DATA__ JSON script."""
        html = """
        <!DOCTYPE html>
        <html>
        <head><title>Next.js App</title></head>
        <body>
            <div id="__next">Empty initial shell</div>
            <script id="__NEXT_DATA__" type="application/json">
            {
                "props": {
                    "pageProps": {
                        "items": [
                            {"id": 1, "url": "/product/gaming-laptop", "title": "Laptop"},
                            {"id": 2, "href": "/category/electronics", "title": "Electronics"}
                        ],
                        "asPath": "/store/home"
                    }
                },
                "page": "/store/home"
            }
            </script>
        </body>
        </html>
        """
        links = discovery.extract_links(html, page_url="https://example.com/", base_domain="example.com")
        assert "https://example.com/product/gaming-laptop" in links
        assert "https://example.com/category/electronics" in links
        assert "https://example.com/store/home" in links

    def test_extract_from_json_ld_breadcrumbs(self, discovery: LinkDiscovery) -> None:
        """Extracts internal links from Schema.org JSON-LD structured data."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": 1,
                        "name": "خانه",
                        "item": "https://example.com/"
                    },
                    {
                        "@type": "ListItem",
                        "position": 2,
                        "name": "محصولات",
                        "item": "https://example.com/products"
                    },
                    {
                        "@type": "ListItem",
                        "position": 3,
                        "name": "لپ‌تاپ",
                        "item": "https://example.com/products/laptops"
                    }
                ]
            }
            </script>
        </head>
        <body>
            <h1>محصولات</h1>
        </body>
        </html>
        """
        links = discovery.extract_links(html, page_url="https://example.com/products", base_domain="example.com")
        assert "https://example.com/products" in links
        assert "https://example.com/products/laptops" in links

    def test_extract_from_area_and_data_attributes(self, discovery: LinkDiscovery) -> None:
        """Extracts links from <area>, data-href, data-url, and data-link tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <body>
            <!-- Image map area -->
            <map name="workmap">
                <area shape="rect" coords="34,44,270,350" href="/map/section-1">
            </map>

            <!-- Card components with data attributes -->
            <div class="product-card" data-href="/items/wireless-mouse">Mouse Card</div>
            <button class="nav-btn" data-url="/categories/peripherals">Peripherals</button>
            <span class="custom-link" data-link="/blog/latest-guide">Guide</span>
            <article data-permalink="/news/tech-2026">Tech News</article>
        </body>
        </html>
        """
        links = discovery.extract_links(html, page_url="https://example.com/", base_domain="example.com")
        assert "https://example.com/map/section-1" in links
        assert "https://example.com/items/wireless-mouse" in links
        assert "https://example.com/categories/peripherals" in links
        assert "https://example.com/blog/latest-guide" in links
        assert "https://example.com/news/tech-2026" in links

    def test_extract_from_canonical_and_alternate_links(self, discovery: LinkDiscovery) -> None:
        """Extracts links from <link rel='canonical'> and <link rel='alternate'> tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <link rel="canonical" href="https://example.com/en/official-product" />
            <link rel="alternate" hreflang="fa" href="https://example.com/fa/official-product" />
        </head>
        <body></body>
        </html>
        """
        links = discovery.extract_links(html, page_url="https://example.com/product", base_domain="example.com")
        assert "https://example.com/en/official-product" in links
        assert "https://example.com/fa/official-product" in links

    def test_extract_from_inline_script_routes(self, discovery: LinkDiscovery) -> None:
        """Extracts client-side SPA routing paths from inline JavaScript bundles."""
        html = """
        <!DOCTYPE html>
        <html>
        <body>
            <div id="app"></div>
            <script>
                const routes = [
                    { path: '/product/rtx-4090', component: ProductView },
                    { path: '/category/graphics-cards', component: CategoryView },
                    { path: '/mag/hardware-review', component: MagView }
                ];
            </script>
        </body>
        </html>
        """
        links = discovery.extract_links(html, page_url="https://example.com/", base_domain="example.com")
        assert "https://example.com/product/rtx-4090" in links
        assert "https://example.com/category/graphics-cards" in links
        assert "https://example.com/mag/hardware-review" in links


# ==============================================================================
# 2. Persian & Unicode URL Canonicalization & Deduplication Tests
# ==============================================================================

class TestPersianAndUnicodeNormalization:
    """Verifies that Persian and Unicode paths normalize and deduplicate cleanly."""

    def test_persian_raw_vs_percent_encoded_unification(self) -> None:
        """Raw UTF-8 Persian path and percent-encoded path normalize to the exact same canonical string."""
        normalizer = URLNormalizer(allowed_domains=["exo.ir"])
        raw_url = "https://exo.ir/دسته-بندی/ماوس-گیمینگ"
        encoded_url = "https://exo.ir/%D8%AF%D8%B3%D8%AA%D9%87-%D8%A8%D9%86%D8%AF%DB%8C/%D9%85%D8%A7%D9%88%D8%B3-%DA%AF%DB%8C%D9%85%DB%8C%D9%86%DA%AF"

        norm_raw = normalizer.normalize(raw_url)
        norm_encoded = normalizer.normalize(encoded_url)

        assert norm_raw is not None
        assert norm_encoded is not None
        assert norm_raw == norm_encoded

    def test_internal_domain_matching_with_persian_subpaths(self) -> None:
        """is_internal and is_same_domain correctly handle Persian/Arabic paths."""
        normalizer = URLNormalizer(allowed_domains=["exo.ir"])
        url = "https://exo.ir/محصولات/کنسول-بازی"
        assert normalizer.is_same_domain(url, "exo.ir")
        assert normalizer.is_internal(url, "exo.ir")


# ==============================================================================
# 3. Crawler Resilience: WAF Headers & Autonomous Browser Fallback
# ==============================================================================

@pytest.mark.asyncio
class TestCrawlerResilienceAndFallback:
    """Verifies CrawlerService browser header enforcement and autonomous Playwright fallback."""

    async def test_crawler_default_headers_contain_browser_signature(self) -> None:
        """Default crawler headers must emulate modern desktop Chrome to avoid WAF blocking."""
        crawler = CrawlerService(root_url="https://exo.ir")
        assert "Mozilla/5.0" in crawler.headers.get("User-Agent", "")
        assert "Chromium" in crawler.headers.get("Sec-Ch-Ua", "")
        assert "fa-IR" in crawler.headers.get("Accept-Language", "")

    async def test_crawler_browser_fallback_triggered_on_403(self) -> None:
        """When static HTTP returns 403 Forbidden, CrawlerService automatically falls back to Playwright."""
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 403
        mock_response.headers = httpx.Headers({})

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        # Mock client.stream context manager
        stream_ctx = MagicMock()
        stream_ctx.__aenter__.return_value = mock_response
        stream_ctx.__aexit__.return_value = None
        mock_client.stream.return_value = stream_ctx

        crawler = CrawlerService(
            root_url="https://example.com",
            client=mock_client,
            enable_browser_fallback=True,
        )

        # Mock robots.txt allowing access
        crawler.robots_checker.can_fetch_detailed = MagicMock(
            return_value=MagicMock(allowed=True, reason="allowed")
        )

        # Mock the browser fallback returning rendered DOM
        rendered_html = "<html><head><title>Bypassed WAF</title></head><body><a href='/page2'>Link</a></body></html>"
        browser_fetch_res = FetchResult(
            html=rendered_html,
            status_code=200,
            final_url="https://example.com/",
            error=None,
        )
        crawler._fetch_via_browser = AsyncMock(return_value=browser_fetch_res)

        result = await crawler._fetch_page(mock_client, "https://example.com/")

        # Must have fallen back to browser and returned 200 with rendered HTML
        assert result.status_code == 200
        assert result.html == rendered_html
        crawler._fetch_via_browser.assert_awaited_once_with("https://example.com/", client=mock_client)

    async def test_crawler_browser_fallback_triggered_on_loading_screen(self) -> None:
        """When static HTTP returns a blank loading screen, CrawlerService promotes to browser rendering."""
        loading_html = """
        <html>
        <head><title>Loading...</title></head>
        <body>
            <div id="preloader" class="loading-spinner">
                <p>در حال بارگذاری اطلاعات لطفا صبر کنید...</p>
            </div>
        </body>
        </html>
        """
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = httpx.Headers({"content-type": "text/html"})
        mock_response.encoding = "utf-8"

        async def aiter_bytes_gen():
            yield loading_html.encode("utf-8")

        mock_response.aiter_bytes = aiter_bytes_gen

        mock_client = AsyncMock(spec=httpx.AsyncClient)
        stream_ctx = MagicMock()
        stream_ctx.__aenter__.return_value = mock_response
        stream_ctx.__aexit__.return_value = None
        mock_client.stream.return_value = stream_ctx

        crawler = CrawlerService(
            root_url="https://example.com",
            client=mock_client,
            enable_browser_fallback=True,
        )
        crawler.robots_checker.can_fetch_detailed = MagicMock(
            return_value=MagicMock(allowed=True, reason="allowed")
        )

        rendered_html = "<html><head><title>Rendered Content</title></head><body><main>Real content loaded</main></body></html>"
        browser_fetch_res = FetchResult(
            html=rendered_html,
            status_code=200,
            final_url="https://example.com/",
            error=None,
        )
        crawler._fetch_via_browser = AsyncMock(return_value=browser_fetch_res)

        result = await crawler._fetch_page(mock_client, "https://example.com/")

        assert result.status_code == 200
        assert result.html == rendered_html
        crawler._fetch_via_browser.assert_awaited_once_with("https://example.com/", client=mock_client)

    async def test_crawler_browser_fallback_on_interstitial_waiting_screen_and_cookie_handoff(self) -> None:
        """When static HTTP returns an ArvanCloud/Cloudflare interstitial challenge (status 200, ~6KB HTML),
        CrawlerService detects it and promotes to browser, transferring challenge cookies to httpx client."""
        from app.services.loading_detector import is_interstitial_or_challenge

        # Real Persian presentation forms used by ArvanCloud / AbrArvan on lioncomputer.com
        arvan_challenge_html = """
        <!DOCTYPE html>
        <html lang="fa">
        <head>
            <meta charset="UTF-8">
            <title>در حال بررسی مرورگر...</title>
            <link rel="stylesheet" href="/cdn-cgi/assets/css/static-pages-2.6.0.css">
        </head>
        <body>
            <h2> \ufea3\ufe8e\ufeed \ufe8d\ufee7\ufe9e\ufee8\ufe8e\ufee0 \ufe8f\ufeea \ufee3\ufeed\ufeed\ufea9 \ufee7\ufe9f\ufeae... </h2>
            <div id="challenge-running">لطفاً چند لحظه صبر نمایید...</div>
            <script>
                var hash_v1 = "abc";
                setTimeout(function(){ location.reload(); }, 2500);
            </script>
        </body>
        </html>
        """
        # Test detection directly
        assert is_interstitial_or_challenge(html=arvan_challenge_html)

        # Standard httpx client with real cookies container
        real_client = httpx.AsyncClient()
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 200
        mock_response.headers = httpx.Headers({"content-type": "text/html"})
        mock_response.encoding = "utf-8"

        async def aiter_bytes_gen():
            yield arvan_challenge_html.encode("utf-8")

        mock_response.aiter_bytes = aiter_bytes_gen

        stream_ctx = MagicMock()
        stream_ctx.__aenter__.return_value = mock_response
        stream_ctx.__aexit__.return_value = None

        with patch.object(real_client, "stream", return_value=stream_ctx):
            crawler = CrawlerService(
                root_url="https://www.lioncomputer.com/",
                client=real_client,
                enable_browser_fallback=True,
            )
            crawler.robots_checker.can_fetch_detailed = MagicMock(
                return_value=MagicMock(allowed=True, reason="allowed")
            )

            # Test actual _fetch_via_browser cookie handoff
            from app.services.extractors.base import EngineResult
            fake_browser_res = EngineResult(engine="playwright", success=True)
            fake_browser_res.raw_html = "<html><head><title>صفحه نخست - لیون کامپیوتر</title></head><body><h1>محصولات</h1></body></html>"
            fake_browser_res.cookies = {"__arcsjs": "token123", "__arcsjsc": "hash456"}

            with patch("app.services.extractors.playwright_engine.PlaywrightEngine.extract", new_callable=AsyncMock) as mock_pw_extract:
                mock_pw_extract.return_value = fake_browser_res

                fetch_res = await crawler._fetch_page(real_client, "https://www.lioncomputer.com/")

                assert fetch_res.status_code == 200
                assert "لیون کامپیوتر" in fetch_res.html
                # Clearance cookies must have transferred to real_client.cookies!
                assert real_client.cookies.get("__arcsjs") == "token123"
                assert real_client.cookies.get("__arcsjsc") == "hash456"

        await real_client.aclose()


# ==============================================================================
# 4. Nested XML Sitemap Index Traversal Tests
# ==============================================================================

@pytest.mark.asyncio
class TestSitemapIndexTraversal:
    """Verifies that SitemapParser traverses nested sitemap indexes and dispatches browser headers."""

    async def test_nested_sitemap_index_discovery(self) -> None:
        """Parses a root <sitemapindex> pointing to child <urlset> sitemaps."""
        sitemap_index_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <sitemap>
                <loc>https://example.com/sitemap-products.xml</loc>
            </sitemap>
        </sitemapindex>
        """

        child_sitemap_xml = b"""<?xml version="1.0" encoding="UTF-8"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
            <url><loc>https://example.com/product/1</loc></url>
            <url><loc>https://example.com/product/2</loc></url>
        </urlset>
        """

        mock_client = AsyncMock(spec=httpx.AsyncClient)

        async def mock_get(url, **kwargs):
            if "sitemap-products.xml" in url:
                return httpx.Response(200, content=child_sitemap_xml, request=httpx.Request("GET", url))
            return httpx.Response(200, content=sitemap_index_xml, request=httpx.Request("GET", url))

        mock_client.get.side_effect = mock_get

        parser = SitemapParser(
            client=mock_client,
            max_urls=100,
            headers={"User-Agent": "Mozilla/5.0 Chrome/124.0.0.0"},
        )
        urls = await parser.parse_sitemap("https://example.com/sitemap_index.xml")

        assert "https://example.com/product/1" in urls
        assert "https://example.com/product/2" in urls
        assert len(urls) == 2


# ==============================================================================
# 5. Full End-to-End Multi-Algorithm Traversal Simulation
# ==============================================================================

@pytest.mark.asyncio
class TestMultiAlgorithmFullTraversal:
    """Verifies that CrawlerService traverses across pages generated by completely different web architectures."""

    async def test_end_to_end_traversal_across_mixed_architectures(self) -> None:
        """Crawl traverses from Root -> Next.js SPA data -> HTML5 interactive cards -> Browser fallback."""
        site_map = {
            "https://example.com/": """
                <html>
                <head><title>Root Home</title></head>
                <body>
                    <!-- Next.js route hydration -->
                    <script id="__NEXT_DATA__" type="application/json">
                    {
                        "props": {
                            "pageProps": {
                                "items": [
                                    {"url": "/spa-catalog"}
                                ]
                            }
                        }
                    }
                    </script>
                </body>
                </html>
            """,
            "https://example.com/spa-catalog": """
                <html>
                <head><title>SPA Catalog</title></head>
                <body>
                    <!-- Interactive HTML5 card elements -->
                    <div class="product-item" data-href="/product/gadget-1">Gadget 1</div>
                    <button data-url="/product/gadget-2">Gadget 2</button>
                </body>
                </html>
            """,
            "https://example.com/product/gadget-1": """
                <html>
                <head><title>Gadget 1</title></head>
                <body>
                    <p>Details about gadget 1</p>
                    <a href="/category/tech">Back to Tech</a>
                </body>
                </html>
            """,
            "https://example.com/product/gadget-2": """
                <html>
                <head><title>Gadget 2</title></head>
                <body>
                    <p>Details about gadget 2</p>
                </body>
                </html>
            """,
            "https://example.com/category/tech": """
                <html>
                <head><title>Tech Category</title></head>
                <body>
                    <p>All tech products</p>
                </body>
                </html>
            """,
        }

        mock_client = AsyncMock(spec=httpx.AsyncClient)

        def mock_stream(method, url, **kwargs):
            clean_url = str(url).rstrip("/")
            if clean_url not in site_map and f"{clean_url}/" in site_map:
                clean_url = f"{clean_url}/"
            html_content = site_map.get(clean_url, "<html><body>404 Not Found</body></html>")
            status = 200 if clean_url in site_map else 404

            resp = MagicMock(spec=httpx.Response)
            resp.status_code = status
            resp.headers = httpx.Headers({"content-type": "text/html"})
            resp.encoding = "utf-8"

            async def aiter_bytes():
                yield html_content.encode("utf-8")

            resp.aiter_bytes = aiter_bytes

            ctx = MagicMock()
            ctx.__aenter__.return_value = resp
            ctx.__aexit__.return_value = None
            return ctx

        mock_client.stream.side_effect = mock_stream

        crawler = CrawlerService(
            root_url="https://example.com/",
            max_depth=3,
            max_pages=10,
            delay=0.0,
            client=mock_client,
            use_sitemap=False,
        )
        crawler.robots_checker.can_fetch_detailed = MagicMock(
            return_value=MagicMock(allowed=True, reason="allowed")
        )

        res = await crawler.discover()

        assert res.total_crawled >= 4
        assert res.total_blocked == 0
        assert "https://example.com/" in res.discovered
        assert "https://example.com/spa-catalog" in res.discovered
        assert "https://example.com/product/gadget-1" in res.discovered
        assert "https://example.com/product/gadget-2" in res.discovered
        assert "https://example.com/category/tech" in res.discovered


# ==============================================================================
# 6. CLI & UI Discovery Alignment Tests
# ==============================================================================

class TestCLIDiscoveryAndExtractorIntegration:
    """Verifies that the CLI discover command and client methods are fully synchronized with UI."""

    def test_cli_discover_parser_configuration(self) -> None:
        """CLI argument parser correctly recognizes discover subcommand and options."""
        from crawlbot.cli import build_parser
        parser = build_parser()

        args = parser.parse_args(["discover", "https://www.lioncomputer.com/", "--max-pages", "100", "--max-depth", "3"])
        assert args.command == "discover"
        assert args.url == "https://www.lioncomputer.com/"
        assert args.max_pages == 100
        assert args.max_depth == 3
        assert args.browser_fallback is True

        args_no_fb = parser.parse_args(["discover", "https://example.com", "--no-browser-fallback"])
        assert args_no_fb.browser_fallback is False

    def test_cli_extract_parser_defaults_to_auto(self) -> None:
        """CLI extract command defaults strategy to auto and supports all engines."""
        from crawlbot.cli import build_parser
        parser = build_parser()

        args = parser.parse_args(["extract", "https://example.com"])
        assert args.strategy == "auto"

    def test_discovery_request_schema_supports_browser_fallback(self) -> None:
        """DiscoveryRequest schema includes enable_browser_fallback with True default."""
        from app.schemas.requests import DiscoveryRequest
        req = DiscoveryRequest(root_url="https://www.lioncomputer.com/")
        assert req.enable_browser_fallback is True

        # Supports alias from frontend/CLI
        req2 = DiscoveryRequest.model_validate({"root_url": "https://example.com", "browser_fallback": False})
        assert req2.enable_browser_fallback is False

