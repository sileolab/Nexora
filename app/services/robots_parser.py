"""Robots.txt parser service for Crawlbot.

This module provides the RobotsChecker class to fetch, parse, and verify URL permissions,
crawl delays, and sitemap locations defined in site robots.txt files.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
from typing import Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)


class RobotsFetchStatus(str, Enum):
    """Fetch outcome classifications for robots.txt under RFC 9309."""
    FETCHED_SUCCESS = "fetched_success"
    NOT_FOUND = "not_found"
    ACCESS_DENIED = "access_denied"
    SERVER_ERROR = "server_error"
    NETWORK_ERROR = "network_error"
    DISABLED = "disabled"


@dataclass
class RobotsDecision:
    """Detailed compliance decision for a candidate crawl URL."""
    allowed: bool
    reason: str
    status: RobotsFetchStatus
    rule_matched: Optional[str] = None
    crawl_delay: Optional[float] = None


class RobotsChecker:
    """Service to fetch, parse, and cache robots.txt compliance rules for web crawling."""

    def __init__(self, failure_policy: str = "lenient") -> None:
        """Initialize the RobotsChecker.

        Args:
            failure_policy: How to handle robots.txt fetch failures:
                'lenient' (default): Allow crawl on 404, 403, or 500 while recording status.
                'strict': Disallow crawl on 403/500/network error (conservative RFC 9309).
        """
        self.failure_policy = failure_policy.lower()
        self._parsers: dict[str, RobotFileParser] = {}
        self._sitemaps: dict[str, list[str]] = {}
        self._crawl_delays: dict[str, dict[str, float]] = {}
        self._fetch_status: dict[str, RobotsFetchStatus] = {}
        self._fetch_error: dict[str, str] = {}

    def _get_domain_key(self, url: str) -> str:
        """Extract a canonical domain key (hostname:port) from a URL.

        Args:
            url: The URL to derive the key from.

        Returns:
            Lowercase hostname (and port if non-default).
        """
        if not url or not isinstance(url, str):
            return ""
        clean_url = url.strip()
        if not clean_url:
            return ""
        if "://" not in clean_url:
            clean_url = f"https://{clean_url}"
        try:
            parsed = urlparse(clean_url)
            hostname = (parsed.hostname or "").lower()
            if not hostname:
                return ""
            port = parsed.port
            if port and not (
                (parsed.scheme == "http" and port == 80)
                or (parsed.scheme == "https" and port == 443)
            ):
                return f"{hostname}:{port}"
            return hostname
        except Exception:
            return ""

    async def fetch_robots(
        self,
        base_url: str,
        client: httpx.AsyncClient,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        """Fetch and parse robots.txt for a domain.

        Handles missing robots.txt (404/network failure) and malformed content gracefully
        by defaulting to permissive access.

        Args:
            base_url: The root URL or domain to fetch robots.txt for.
            client: The httpx.AsyncClient used for network requests.
            headers: Optional headers (e.g. browser headers) for WAF compatibility.
        """
        domain_key = self._get_domain_key(base_url)
        if not domain_key:
            return

        clean_base = base_url.strip()
        if "://" not in clean_base:
            clean_base = f"https://{clean_base}"

        try:
            parsed = urlparse(clean_base)
            scheme = parsed.scheme if parsed.scheme in ("http", "https") else "https"
            netloc = parsed.netloc or parsed.path.split("/")[0]
            robots_url = f"{scheme}://{netloc}/robots.txt"
        except Exception as exc:
            logger.warning("Failed to construct robots.txt URL from %s: %s", base_url, exc)
            self._set_permissive_parser(domain_key)
            return

        try:
            response = await client.get(robots_url, headers=headers, follow_redirects=True, timeout=10.0)
            if response.status_code == 200:
                self._fetch_status[domain_key] = RobotsFetchStatus.FETCHED_SUCCESS
                self._parse_robots_content(domain_key, response.text)
            elif response.status_code == 404:
                self._fetch_status[domain_key] = RobotsFetchStatus.NOT_FOUND
                self._fetch_error[domain_key] = "404 Not Found"
                self._set_permissive_parser(domain_key)
            elif response.status_code in (401, 403):
                self._fetch_status[domain_key] = RobotsFetchStatus.ACCESS_DENIED
                self._fetch_error[domain_key] = f"HTTP {response.status_code} Forbidden"
                if self.failure_policy == "strict":
                    self._set_restrictive_parser(domain_key)
                else:
                    self._set_permissive_parser(domain_key)
            elif response.status_code >= 500:
                self._fetch_status[domain_key] = RobotsFetchStatus.SERVER_ERROR
                self._fetch_error[domain_key] = f"HTTP {response.status_code} Server Error"
                if self.failure_policy == "strict":
                    self._set_restrictive_parser(domain_key)
                else:
                    self._set_permissive_parser(domain_key)
            else:
                self._fetch_status[domain_key] = RobotsFetchStatus.ACCESS_DENIED
                self._fetch_error[domain_key] = f"HTTP {response.status_code}"
                if self.failure_policy == "strict":
                    self._set_restrictive_parser(domain_key)
                else:
                    self._set_permissive_parser(domain_key)
        except Exception as exc:
            logger.debug("Could not fetch robots.txt for %s: %s", domain_key, exc)
            self._fetch_status[domain_key] = RobotsFetchStatus.NETWORK_ERROR
            self._fetch_error[domain_key] = str(exc)
            if self.failure_policy == "strict":
                self._set_restrictive_parser(domain_key)
            else:
                self._set_permissive_parser(domain_key)

    def _set_permissive_parser(self, domain_key: str) -> None:
        """Configure a permissive parser that allows all crawling for the given domain."""
        parser = RobotFileParser()
        parser.allow_all = True
        parser.modified()
        self._parsers[domain_key] = parser
        self._sitemaps.setdefault(domain_key, [])
        self._crawl_delays.setdefault(domain_key, {})

    def _set_restrictive_parser(self, domain_key: str) -> None:
        """Configure a restrictive parser that disallows crawling for the given domain."""
        parser = RobotFileParser()
        parser.disallow_all = True
        parser.modified()
        self._parsers[domain_key] = parser
        self._sitemaps.setdefault(domain_key, [])
        self._crawl_delays.setdefault(domain_key, {})

    def _parse_robots_content(self, domain_key: str, content: str) -> None:
        """Parse raw robots.txt text and populate parser, sitemaps, and crawl delays.

        Args:
            domain_key: The canonical domain key.
            content: Raw robots.txt text content.
        """
        parser = RobotFileParser()
        lines = content.splitlines()
        try:
            parser.parse(lines)
            parser.modified()
            # Conform to RFC 9309 (longer path matches take precedence, allow wins over disallow)
            all_entries = list(parser.entries)
            if parser.default_entry:
                all_entries.append(parser.default_entry)
            for entry in all_entries:
                if hasattr(entry, "rulelines"):
                    entry.rulelines.sort(key=lambda r: (len(getattr(r, "path", "")), getattr(r, "allowance", False)), reverse=True)
        except Exception as exc:
            logger.warning("Error parsing robots.txt for %s: %s", domain_key, exc)
            parser.allow_all = True
            parser.modified()

        self._parsers[domain_key] = parser

        # Custom extraction for sitemaps and float crawl-delays
        sitemaps: list[str] = []
        crawl_delays: dict[str, float] = {}

        # 0: waiting for user-agent, 1: reading user-agent(s), 2: reading rules
        state = 0
        current_agents: list[str] = []
        for raw_line in lines:
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                state = 0
                current_agents = []
                continue
            if ":" not in line:
                continue

            field, val = line.split(":", 1)
            field = field.strip().lower()
            val = val.strip()

            if field == "user-agent":
                if state == 2:
                    current_agents = []
                state = 1
                agent = val.lower()
                current_agents.append(agent)
            elif field == "sitemap":
                if val and val not in sitemaps:
                    sitemaps.append(val)
            elif field == "crawl-delay":
                state = 2
                try:
                    delay = float(val)
                    agents_to_set = current_agents if current_agents else ["*"]
                    for ag in agents_to_set:
                        crawl_delays[ag] = delay
                except ValueError:
                    pass
            elif field in ("allow", "disallow"):
                state = 2

        # Also incorporate any sitemaps parsed by RobotFileParser itself
        try:
            official_sitemaps = parser.site_maps()
            if official_sitemaps:
                for sm in official_sitemaps:
                    if sm and sm not in sitemaps:
                        sitemaps.append(sm)
        except Exception:
            pass

        self._sitemaps[domain_key] = sitemaps
        self._crawl_delays[domain_key] = crawl_delays

    def can_fetch_detailed(self, url: str, user_agent: str = "*") -> RobotsDecision:
        """Evaluate URL compliance with detailed RFC 9309 diagnostic report.

        Distinguishes explicit rule allowances, disallowances, 404 missing status,
        and fetch access/server errors.
        """
        if not url:
            return RobotsDecision(
                allowed=True,
                reason="empty_url",
                status=RobotsFetchStatus.DISABLED,
            )

        domain_key = self._get_domain_key(url)
        status = self._fetch_status.get(domain_key, RobotsFetchStatus.NOT_FOUND)
        parser = self._parsers.get(domain_key)
        delay = self.get_crawl_delay(url, user_agent)

        if not parser:
            return RobotsDecision(
                allowed=True,
                reason="no_robots_parser_available",
                status=status,
                crawl_delay=delay,
            )

        if status == RobotsFetchStatus.ACCESS_DENIED:
            allowed = (self.failure_policy != "strict")
            reason = f"robots_access_denied: {self._fetch_error.get(domain_key, '403 Forbidden')}"
            return RobotsDecision(
                allowed=allowed,
                reason=reason,
                status=status,
                crawl_delay=delay,
            )

        if status == RobotsFetchStatus.SERVER_ERROR:
            allowed = (self.failure_policy != "strict")
            reason = f"robots_server_error: {self._fetch_error.get(domain_key, '5xx Server Error')}"
            return RobotsDecision(
                allowed=allowed,
                reason=reason,
                status=status,
                crawl_delay=delay,
            )

        if status == RobotsFetchStatus.NETWORK_ERROR:
            allowed = (self.failure_policy != "strict")
            reason = f"robots_network_error: {self._fetch_error.get(domain_key, 'Connection failed')}"
            return RobotsDecision(
                allowed=allowed,
                reason=reason,
                status=status,
                crawl_delay=delay,
            )

        if status == RobotsFetchStatus.NOT_FOUND:
            return RobotsDecision(
                allowed=True,
                reason="robots_not_found: 404 allows crawling (RFC 9309)",
                status=status,
                crawl_delay=delay,
            )

        # Status is FETCHED_SUCCESS: check parsed rules
        try:
            can_fetch = bool(parser.can_fetch(user_agent, url))
        except Exception:
            can_fetch = True

        if can_fetch:
            return RobotsDecision(
                allowed=True,
                reason="explicit_allow: Permitted by robots.txt rules",
                status=status,
                crawl_delay=delay,
            )
        else:
            return RobotsDecision(
                allowed=False,
                reason="explicit_disallow: Disallowed by robots.txt rule",
                status=status,
                crawl_delay=delay,
            )

    def is_allowed(self, url: str, user_agent: str = "*") -> bool:
        """Check if URL is allowed by robots.txt.

        Args:
            url: The URL to evaluate.
            user_agent: The crawler user agent identifier.

        Returns:
            True if crawling is permitted, False otherwise.
        """
        return self.can_fetch_detailed(url, user_agent).allowed

    def get_sitemaps(self, base_url: str) -> list[str]:
        """Get sitemap URLs extracted from robots.txt.

        Args:
            base_url: The domain or base URL.

        Returns:
            List of sitemap URLs found in robots.txt.
        """
        domain_key = self._get_domain_key(base_url)
        sitemaps = self._sitemaps.get(domain_key)
        if sitemaps is not None:
            return list(sitemaps)

        parser = self._parsers.get(domain_key)
        if parser:
            try:
                found = parser.site_maps()
                return list(found) if found else []
            except Exception:
                return []

        return []

    def get_crawl_delay(self, base_url: str, user_agent: str = "*") -> float | None:
        """Get crawl delay from robots.txt.

        Args:
            base_url: The domain or base URL.
            user_agent: The crawler user agent.

        Returns:
            Crawl delay in seconds as float, or None if unspecified.
        """
        domain_key = self._get_domain_key(base_url)
        delays = self._crawl_delays.get(domain_key)
        if delays is not None:
            ua_lower = user_agent.lower()
            if ua_lower in delays:
                return delays[ua_lower]
            if "*" in delays:
                return delays["*"]

        parser = self._parsers.get(domain_key)
        if parser:
            try:
                delay = parser.crawl_delay(user_agent)
                if delay is not None:
                    return float(delay)
            except Exception:
                return None

        return None
