"""HTML Link and Metadata Discovery Service for Crawlbot.

This module provides the LinkDiscovery class to extract, normalize, and filter internal
links and metadata (title, meta description, canonical URL, language) from HTML documents.
"""

from __future__ import annotations

import logging
import posixpath
import re
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from .url_normalizer import URLNormalizer

logger = logging.getLogger(__name__)

EXCLUDED_EXTENSIONS: frozenset[str] = frozenset({
    # Images and icons
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".bmp",
    ".ico",
    ".tiff",
    ".tif",
    ".avif",
    # Documents and spreadsheets
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".odt",
    ".ods",
    ".odp",
    ".rtf",
    ".txt",
    ".csv",
    # Archives and compressed formats
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".rar",
    ".7z",
    ".bz2",
    ".xz",
    ".iso",
    # Media: audio and video
    ".mp3",
    ".mp4",
    ".wav",
    ".avi",
    ".mov",
    ".wmv",
    ".flv",
    ".mkv",
    ".webm",
    ".m4a",
    ".ogg",
    ".ogv",
    # Stylesheets, scripts, fonts, and data feeds
    ".css",
    ".js",
    ".json",
    ".xml",
    ".rss",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    # Binaries and installers
    ".exe",
    ".dmg",
    ".apk",
    ".msi",
    ".bin",
    ".deb",
    ".rpm",
})


class LinkDiscovery:
    """Service to parse HTML pages, discover normalized internal links, and extract metadata."""

    def __init__(self, normalizer: URLNormalizer) -> None:
        """Initialize the LinkDiscovery service with a URLNormalizer instance.

        Args:
            normalizer: The URLNormalizer used to normalize and scope URLs.
        """
        self.normalizer: URLNormalizer = normalizer

    def extract_links(self, html: str, page_url: str, base_domain: str) -> list[str]:
        """Extract and normalize all internal links from HTML.

        Filters out non-page links (mailto:, tel:, javascript:, data:, anchors, and asset files).

        Args:
            html: Raw HTML content string.
            page_url: The URL of the page being parsed (used as base URL for relative links).
            base_domain: The primary domain to scope internal links against.

        Returns:
            A deduplicated list of normalized internal page URLs preserving order of appearance.
        """
        if not html or not isinstance(html, str):
            return []

        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as exc:
            logger.warning("Failed to parse HTML for links at %s: %s", page_url, exc)
            return []

        discovered_links: list[str] = []
        seen: set[str] = set()

        def _add_candidate(raw: Optional[str]) -> None:
            if not raw or not isinstance(raw, str):
                return
            clean = raw.strip()
            if not clean or clean.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
                return
            # Normalize against page_url
            normalized = self.normalizer.normalize(clean, base_url=page_url)
            if not normalized:
                return
            # Check excluded extension
            try:
                parsed_path = urlparse(normalized).path.lower()
                _, ext = posixpath.splitext(parsed_path)
                if ext in EXCLUDED_EXTENSIONS:
                    return
                # Skip framework asset/internal paths
                if any(p in parsed_path for p in ("/_next/static/", "/_nuxt/", "/wp-json/oembed")):
                    return
            except Exception:
                return

            # Filter to internal links only
            if not self.normalizer.is_internal(normalized, base_domain):
                return

            if normalized not in seen:
                seen.add(normalized)
                discovered_links.append(normalized)

        # 1. Standard anchor links <a href="...">
        for anchor in soup.find_all("a", href=True):
            _add_candidate(anchor.get("href"))

        # 2. Image map area links <area href="...">
        for area in soup.find_all("area", href=True):
            _add_candidate(area.get("href"))

        # 3. Canonical and alternate links <link rel="canonical" ...>
        for link_tag in soup.find_all("link", href=True):
            rel = link_tag.get("rel", [])
            rel_list = [r.lower() for r in (rel if isinstance(rel, list) else rel.split())]
            if any(r in ("canonical", "alternate") for r in rel_list):
                _add_candidate(link_tag.get("href"))

        # 4. Interactive HTML elements with data-href or data-url attributes
        for el in soup.find_all(attrs={"data-href": True}):
            _add_candidate(el.get("data-href"))
        for el in soup.find_all(attrs={"data-url": True}):
            _add_candidate(el.get("data-url"))
        for el in soup.find_all(attrs={"data-link": True}):
            _add_candidate(el.get("data-link"))
        for el in soup.find_all(attrs={"data-permalink": True}):
            _add_candidate(el.get("data-permalink"))

        # 5. SPA and Framework metadata (Next.js __NEXT_DATA__, JSON-LD, etc.)
        self._extract_spa_and_json_links(soup, page_url, base_domain, _add_candidate)

        return discovered_links

    def _extract_spa_and_json_links(
        self,
        soup: BeautifulSoup,
        page_url: str,
        base_domain: str,
        add_candidate: Any,
    ) -> None:
        """Extract links embedded in SPA route manifests, Next.js hydration data, and JSON-LD."""
        import json

        # A. Next.js __NEXT_DATA__
        next_data_tag = soup.find("script", id="__NEXT_DATA__")
        if next_data_tag and next_data_tag.string:
            try:
                data = json.loads(next_data_tag.string)
                self._crawl_json_for_links(data, add_candidate)
            except Exception:
                pass

        # B. JSON-LD scripts (Schema.org BreadcrumbList, ItemList, Product, WebPage)
        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            if script.string:
                try:
                    data = json.loads(script.string)
                    self._crawl_json_for_links(data, add_candidate)
                except Exception:
                    pass

        # C. Regex extraction for common SPA route paths in inline scripts
        for script in soup.find_all("script"):
            # Skip external script tags or next-data
            if script.get("src") or script.get("id") == "__NEXT_DATA__":
                continue
            script_text = script.string or ""
            if not script_text or len(script_text) > 100000:
                continue

            # Look for quoted route paths like "/product/..." or "/category/..." or "/mag/..."
            route_matches = re.findall(
                r'["\'](/(?:product|products|item|items|category|categories|tag|tags|brand|brands|blog|mag|article|articles|page|p|c)/[a-zA-Z0-9_\-\u0600-\u06FF/%]+)["\']',
                script_text,
            )
            for m in route_matches[:100]:
                add_candidate(m)

    def _crawl_json_for_links(self, data: Any, add_candidate: Any, depth: int = 0) -> None:
        """Recursively inspect parsed JSON structures for candidate URLs."""
        if depth > 10:
            return

        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str):
                    k_lower = k.lower()
                    if k_lower in ("url", "href", "aspath", "pathname", "canonical", "link", "targeturl", "item"):
                        add_candidate(v)
                    elif v.startswith(("http://", "https://", "/")) and not v.endswith((".js", ".css", ".png", ".jpg", ".svg", ".json")):
                        # Check if string looks like an internal path
                        if re.match(r"^/[a-zA-Z0-9_\-\u0600-\u06FF/%]+$", v):
                            add_candidate(v)
                elif isinstance(v, (dict, list)):
                    self._crawl_json_for_links(v, add_candidate, depth + 1)
        elif isinstance(data, list):
            for item in data[:200]:
                if isinstance(item, str):
                    if item.startswith(("http://", "https://", "/")):
                        add_candidate(item)
                elif isinstance(item, (dict, list)):
                    self._crawl_json_for_links(item, add_candidate, depth + 1)

    def extract_title(self, html: str) -> str | None:
        """Extract page title from HTML.

        Checks <title> tag first, falling back to OpenGraph and Twitter meta tags.

        Args:
            html: Raw HTML content string.

        Returns:
            Page title string if found and non-empty, otherwise None.
        """
        if not html or not isinstance(html, str):
            return None

        try:
            soup = BeautifulSoup(html, "html.parser")
            title_tag = soup.find("title")
            if title_tag:
                title_text = title_tag.get_text(strip=True)
                if title_text:
                    return title_text

            # Fallback to og:title or twitter:title
            og_title = soup.find("meta", attrs={"property": "og:title"}) or soup.find(
                "meta", attrs={"name": "twitter:title"}
            )
            if og_title and og_title.get("content"):
                content = str(og_title["content"]).strip()
                if content:
                    return content
        except Exception as exc:
            logger.debug("Failed to extract title from HTML: %s", exc)

        return None

    def extract_meta_description(self, html: str) -> str | None:
        """Extract meta description from HTML.

        Checks <meta name="description">, falling back to OpenGraph and Twitter description tags.

        Args:
            html: Raw HTML content string.

        Returns:
            Description string if found and non-empty, otherwise None.
        """
        if not html or not isinstance(html, str):
            return None

        try:
            soup = BeautifulSoup(html, "html.parser")
            meta_desc = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
            if meta_desc and meta_desc.get("content"):
                content = str(meta_desc["content"]).strip()
                if content:
                    return content

            # Fallback to og:description or twitter:description
            og_desc = soup.find("meta", attrs={"property": "og:description"}) or soup.find(
                "meta", attrs={"name": "twitter:description"}
            )
            if og_desc and og_desc.get("content"):
                content = str(og_desc["content"]).strip()
                if content:
                    return content
        except Exception as exc:
            logger.debug("Failed to extract meta description from HTML: %s", exc)

        return None

    def extract_canonical_url(self, html: str) -> str | None:
        """Extract canonical URL from <link rel='canonical'>.

        Args:
            html: Raw HTML content string.

        Returns:
            Canonical URL href string if found and non-empty, otherwise None.
        """
        if not html or not isinstance(html, str):
            return None

        try:
            soup = BeautifulSoup(html, "html.parser")
            canonical_tag = soup.find(
                "link",
                attrs={
                    "rel": lambda r: r
                    and (
                        "canonical" in r
                        if isinstance(r, list)
                        else "canonical" in r.lower().split()
                    )
                },
            )
            if canonical_tag and canonical_tag.get("href"):
                content = str(canonical_tag["href"]).strip()
                if content:
                    return content
        except Exception as exc:
            logger.debug("Failed to extract canonical URL from HTML: %s", exc)

        return None

    def extract_language(self, html: str) -> str | None:
        """Extract language from <html lang='...'> or <meta> tags.

        Checks <html lang="..."> / xml:lang, then <meta http-equiv="content-language">,
        and finally <meta property="og:locale">.

        Args:
            html: Raw HTML content string.

        Returns:
            Extracted language code (e.g., 'en', 'en-US') if found, otherwise None.
        """
        if not html or not isinstance(html, str):
            return None

        try:
            soup = BeautifulSoup(html, "html.parser")
            html_tag = soup.find("html")
            if html_tag:
                lang = html_tag.get("lang") or html_tag.get("xml:lang")
                if lang and str(lang).strip():
                    return str(lang).strip()

            # Fallback to <meta http-equiv="content-language" content="...">
            meta_lang = soup.find(
                "meta",
                attrs={"http-equiv": re.compile(r"^content-language$", re.I)},
            )
            if meta_lang and meta_lang.get("content"):
                content = str(meta_lang["content"]).strip()
                if content:
                    return content

            # Fallback to <meta property="og:locale" content="...">
            og_locale = soup.find("meta", attrs={"property": "og:locale"})
            if og_locale and og_locale.get("content"):
                content = str(og_locale["content"]).strip()
                if content:
                    return content
        except Exception as exc:
            logger.debug("Failed to extract language from HTML: %s", exc)

        return None
