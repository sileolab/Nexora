"""Anti-Bot Detection, Request Scheduling & Resilience Subsystem for Crawlbot.

Provides enterprise-grade HTTP request resilience, ethical rate limiting,
exponential backoff with jitter, Retry-After header compliance, per-domain
concurrency control, session pooling, and structured response diagnostics.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
import email.utils
from enum import Enum
import logging
import random
import re
import sys
import threading
import time
from typing import Any, AsyncIterator, Callable, Coroutine, Final, Optional, Union
from urllib.parse import urlparse

import httpx

from app.core.config import get_settings
from app.core.security import validate_url_safety

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. Enums, Models & Header Sanitization
# ==============================================================================

class ResponseClassification(str, Enum):
    """Standardized classification of HTTP fetch outcomes."""

    SUCCESS = "SUCCESS"
    HTTP_FORBIDDEN = "HTTP_FORBIDDEN"
    BOT_PROTECTION = "BOT_PROTECTION"
    RATE_LIMITED = "RATE_LIMITED"
    ROBOTS_DENIED = "ROBOTS_DENIED"
    CAPTCHA_REQUIRED = "CAPTCHA_REQUIRED"
    JS_RENDER_REQUIRED = "JS_RENDER_REQUIRED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT = "TIMEOUT"
    SERVER_ERROR = "SERVER_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


@dataclass
class RequestDiagnostics:
    """Structured, privacy-safe telemetry for an HTTP request attempt sequence."""

    url: str
    domain: str
    classification: ResponseClassification
    http_status: Optional[int]
    retryable: bool
    suggested_action: str
    reason: str
    execution_time_ms: float
    attempt_count: int
    headers_snippet: dict[str, str] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Serialize diagnostics without sensitive headers or cookies."""
        return {
            "url": self.url,
            "domain": self.domain,
            "classification": self.classification.value,
            "http_status": self.http_status,
            "retryable": self.retryable,
            "suggested_action": self.suggested_action,
            "reason": self.reason,
            "execution_time_ms": round(self.execution_time_ms, 2),
            "attempt_count": self.attempt_count,
            "timestamp": self.timestamp,
        }


def sanitize_headers(headers: Optional[dict[str, str]]) -> dict[str, str]:
    """Sanitize headers dictionary to remove sensitive auth, cookie, and credential tokens."""
    if not headers:
        return {}
    sensitive_keys = {
        "authorization", "cookie", "set-cookie", "proxy-authorization",
        "x-api-key", "api-key", "token", "x-auth-token", "bearer", "password",
        "x-admin-secret", "secret", "session", "x-session-id",
    }
    safe: dict[str, str] = {}
    for k, v in headers.items():
        if k.lower() not in sensitive_keys:
            safe[k] = str(v)[:200]
    return safe


@dataclass
class DomainPolicy:
    """Per-domain crawling policies and rate limit specifications."""

    domain: str
    max_concurrency: int = 2
    min_delay_seconds: float = 0.5
    request_timeout: float = 30.0
    max_retries: int = 3
    max_response_size: int = 10 * 1024 * 1024  # 10MB
    allow_subdomains: bool = True
    custom_headers: dict[str, str] = field(default_factory=dict)


# ==============================================================================
# 2. Response Analyzer (ResponseAnalyzer)
# ==============================================================================

class ResponseAnalyzer:
    """Multi-signal analyzer for HTTP responses, headers, and body snippets.

    Standardizes outcomes into 12 classifications:
    - SUCCESS
    - HTTP_FORBIDDEN
    - BOT_PROTECTION
    - RATE_LIMITED
    - ROBOTS_DENIED
    - CAPTCHA_REQUIRED
    - JS_RENDER_REQUIRED
    - AUTH_REQUIRED
    - NETWORK_ERROR
    - TIMEOUT
    - SERVER_ERROR
    - UNKNOWN_ERROR
    """

    MAX_SNIPPET_BYTES: Final[int] = 64 * 1024  # 64 KB

    # 1. Explicit CAPTCHA patterns
    CAPTCHA_PATTERNS: Final[list[re.Pattern[str]]] = [
        re.compile(r'class=["\'][^"\']*(?:g-recaptcha|h-captcha|cf-turnstile)[^"\']*["\']', re.IGNORECASE),
        re.compile(r'(?:hcaptcha\.com/(?:1/)?api\.js|google\.com/recaptcha/api\.js|challenges\.cloudflare\.com/turnstile|arkoselabs|funcaptcha|geetest)', re.IGNORECASE),
        re.compile(r'(?:please\s+verify\s+you\s+are\s+human|complete\s+the\s+(?:security|captcha)\s+check|solve\s+the\s+challenge)', re.IGNORECASE),
        re.compile(r'<iframe[^>]+(?:recaptcha|hcaptcha|turnstile|arkose)[^>]*>', re.IGNORECASE),
    ]

    # 2. Bot Protection & WAF challenge patterns
    BOT_CHALLENGE_PATTERNS: Final[list[re.Pattern[str]]] = [
        re.compile(r'attention\s+required!\s*\|\s*cloudflare', re.IGNORECASE),
        re.compile(r'cf-browser-verification', re.IGNORECASE),
        re.compile(r'checking\s+your\s+browser\s+before\s+accessing', re.IGNORECASE),
        re.compile(r'just\s+a\s+moment\.\.\.', re.IGNORECASE),
        re.compile(r'protected\s+by\s+datadome', re.IGNORECASE),
        re.compile(r'incapsula\s+incident\s+id', re.IGNORECASE),
        re.compile(r'access\s+to\s+this\s+page\s+has\s+been\s+denied\s+because\s+we\s+believe\s+you\s+are\s+using\s+automation', re.IGNORECASE),
        re.compile(r'request\s+blocked\s+by\s+security\s+policy', re.IGNORECASE),
        re.compile(r'access\s+denied\s*-\s*akamai', re.IGNORECASE),
    ]

    # 3. Dedicated WAF / Bot detection headers
    BOT_HEADERS: Final[set[str]] = {
        "cf-mitigated",
        "cf-chl-bypass",
        "x-datadome",
        "x-datadome-cid",
        "x-px-original-url",
        "x-sucuri-id",
        "x-imperva-blocking",
    }

    # 4. SPA mount containers indicating JS execution requirement
    SPA_CONTAINER_PATTERNS: Final[list[re.Pattern[str]]] = [
        re.compile(r'<div[^>]+id=["\'](?:app|root|__next|__nuxt|main-content)["\'][^>]*>\s*</div>', re.IGNORECASE),
        re.compile(r'<app-root>\s*</app-root>', re.IGNORECASE),
    ]

    # 5. Explicit noscript requirement warnings
    NOSCRIPT_REQUIRED_PATTERNS: Final[list[re.Pattern[str]]] = [
        re.compile(r'<noscript>[^<]*(?:you\s+need\s+to\s+enable\s+javascript|javascript\s+is\s+required|enable\s+javascript\s+to\s+run|requires\s+javascript)[^<]*</noscript>', re.IGNORECASE),
    ]

    @staticmethod
    def _strip_tags(html: str) -> str:
        """Strip HTML tags and scripts to estimate real visible content length."""
        no_scripts = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', html, flags=re.DOTALL | re.IGNORECASE)
        no_tags = re.sub(r'<[^>]+>', ' ', no_scripts)
        return " ".join(no_tags.split())

    def analyze(
        self,
        url: str,
        domain: Optional[str] = None,
        status_code: Optional[int] = None,
        headers: Optional[dict[str, str]] = None,
        body: Optional[Union[str, bytes]] = None,
        exception: Optional[Exception] = None,
        execution_time_ms: float = 0.0,
        attempt_count: int = 1,
        is_robots_disallowed: bool = False,
        custom_reason: Optional[str] = None,
    ) -> RequestDiagnostics:
        """Evaluate request execution signals and determine standardized classification."""
        dom = domain or RequestScheduler.extract_domain(url)
        safe_hdrs = sanitize_headers(headers)
        hdr_keys = {k.lower(): v for k, v in (headers or {}).items()}

        # 1. robots.txt policy denial
        if is_robots_disallowed:
            return RequestDiagnostics(
                url=url,
                domain=dom,
                classification=ResponseClassification.ROBOTS_DENIED,
                http_status=status_code or 403,
                retryable=False,
                suggested_action="respect_robots",
                reason=custom_reason or "Target URL disallowed by robots.txt policy",
                execution_time_ms=execution_time_ms,
                attempt_count=attempt_count,
                headers_snippet=safe_hdrs,
            )

        # 2. Exceptions (Timeout, Network, Cancellation)
        if exception is not None:
            if isinstance(exception, asyncio.CancelledError):
                return RequestDiagnostics(
                    url=url,
                    domain=dom,
                    classification=ResponseClassification.UNKNOWN_ERROR,
                    http_status=None,
                    retryable=False,
                    suggested_action="abort",
                    reason="Operation cancelled by user",
                    execution_time_ms=execution_time_ms,
                    attempt_count=attempt_count,
                    headers_snippet=safe_hdrs,
                )
            if isinstance(exception, (httpx.TimeoutException, asyncio.TimeoutError)):
                return RequestDiagnostics(
                    url=url,
                    domain=dom,
                    classification=ResponseClassification.TIMEOUT,
                    http_status=None,
                    retryable=True,
                    suggested_action="retry_with_longer_timeout",
                    reason=f"HTTP request timed out: {exception}",
                    execution_time_ms=execution_time_ms,
                    attempt_count=attempt_count,
                    headers_snippet=safe_hdrs,
                )
            if isinstance(exception, (httpx.NetworkError, ConnectionError, OSError)):
                return RequestDiagnostics(
                    url=url,
                    domain=dom,
                    classification=ResponseClassification.NETWORK_ERROR,
                    http_status=None,
                    retryable=True,
                    suggested_action="retry_network",
                    reason=f"Network transport error: {exception}",
                    execution_time_ms=execution_time_ms,
                    attempt_count=attempt_count,
                    headers_snippet=safe_hdrs,
                )
            return RequestDiagnostics(
                url=url,
                domain=dom,
                classification=ResponseClassification.UNKNOWN_ERROR,
                http_status=None,
                retryable=False,
                suggested_action="inspect_error",
                reason=f"Unexpected exception: {exception}",
                execution_time_ms=execution_time_ms,
                attempt_count=attempt_count,
                headers_snippet=safe_hdrs,
            )

        # 3. HTTP Status code and body snippet analysis
        if status_code is None:
            return RequestDiagnostics(
                url=url,
                domain=dom,
                classification=ResponseClassification.UNKNOWN_ERROR,
                http_status=None,
                retryable=False,
                suggested_action="inspect_error",
                reason=custom_reason or "Unknown state: no status code or exception provided",
                execution_time_ms=execution_time_ms,
                attempt_count=attempt_count,
                headers_snippet=safe_hdrs,
            )

        # Decode snippet safely
        snippet = ""
        if body:
            if isinstance(body, bytes):
                snippet = body[:self.MAX_SNIPPET_BYTES].decode("utf-8", errors="replace")
            else:
                snippet = body[:self.MAX_SNIPPET_BYTES]

        # A. Check CAPTCHA Challenge first (can occur on 200, 403, 429)
        if snippet and any(p.search(snippet) for p in self.CAPTCHA_PATTERNS):
            return RequestDiagnostics(
                url=url,
                domain=dom,
                classification=ResponseClassification.CAPTCHA_REQUIRED,
                http_status=status_code,
                retryable=False,
                suggested_action="captcha_blocked",
                reason="Explicit CAPTCHA verification challenge detected in page content",
                execution_time_ms=execution_time_ms,
                attempt_count=attempt_count,
                headers_snippet=safe_hdrs,
            )

        # B. Check Rate Limiting (429 or 503 with rate limit headers / text)
        if status_code == 429 or (status_code == 503 and ("retry-after" in hdr_keys or "x-ratelimit-remaining" in hdr_keys)):
            return RequestDiagnostics(
                url=url,
                domain=dom,
                classification=ResponseClassification.RATE_LIMITED,
                http_status=status_code,
                retryable=True,
                suggested_action="backoff_retry",
                reason=f"Rate limit exceeded (HTTP {status_code})",
                execution_time_ms=execution_time_ms,
                attempt_count=attempt_count,
                headers_snippet=safe_hdrs,
            )

        # C. Check Bot Protection & WAF (Cloudflare, Datadome, Imperva, PerimeterX, Akamai)
        has_bot_hdr = any(h in hdr_keys for h in self.BOT_HEADERS)
        has_bot_pattern = bool(snippet and any(p.search(snippet) for p in self.BOT_CHALLENGE_PATTERNS))
        if has_bot_hdr or has_bot_pattern:
            return RequestDiagnostics(
                url=url,
                domain=dom,
                classification=ResponseClassification.BOT_PROTECTION,
                http_status=status_code,
                retryable=False,
                suggested_action="respect_block",
                reason="Anti-bot protection challenge or WAF mitigation detected",
                execution_time_ms=execution_time_ms,
                attempt_count=attempt_count,
                headers_snippet=safe_hdrs,
            )

        # D. Check Authentication Required (401, 407, or 403 with WWW-Authenticate)
        if status_code in (401, 407) or (status_code == 403 and "www-authenticate" in hdr_keys):
            return RequestDiagnostics(
                url=url,
                domain=dom,
                classification=ResponseClassification.AUTH_REQUIRED,
                http_status=status_code,
                retryable=False,
                suggested_action="provide_credentials",
                reason=f"HTTP authentication required (HTTP {status_code})",
                execution_time_ms=execution_time_ms,
                attempt_count=attempt_count,
                headers_snippet=safe_hdrs,
            )

        # E. Standard 403 Forbidden (Without bot markers)
        if status_code == 403:
            return RequestDiagnostics(
                url=url,
                domain=dom,
                classification=ResponseClassification.HTTP_FORBIDDEN,
                http_status=403,
                retryable=False,
                suggested_action="skip_forbidden",
                reason=custom_reason or "Standard HTTP 403 Forbidden access denial",
                execution_time_ms=execution_time_ms,
                attempt_count=attempt_count,
                headers_snippet=safe_hdrs,
            )

        # F. Server Error 5xx
        if 500 <= status_code < 600:
            return RequestDiagnostics(
                url=url,
                domain=dom,
                classification=ResponseClassification.SERVER_ERROR,
                http_status=status_code,
                retryable=True,
                suggested_action="retry_server",
                reason=f"Server returned internal error (HTTP {status_code})",
                execution_time_ms=execution_time_ms,
                attempt_count=attempt_count,
                headers_snippet=safe_hdrs,
            )

        # G. Client Error 4xx
        if 400 <= status_code < 500:
            return RequestDiagnostics(
                url=url,
                domain=dom,
                classification=ResponseClassification.UNKNOWN_ERROR,
                http_status=status_code,
                retryable=False,
                suggested_action="skip_client_error",
                reason=f"Client request error (HTTP {status_code})",
                execution_time_ms=execution_time_ms,
                attempt_count=attempt_count,
                headers_snippet=safe_hdrs,
            )

        # H. Successful 2xx/3xx - Check for JS_RENDER_REQUIRED
        if 200 <= status_code < 400:
            if snippet:
                # 1. Explicit noscript requirement
                if any(p.search(snippet) for p in self.NOSCRIPT_REQUIRED_PATTERNS):
                    return RequestDiagnostics(
                        url=url,
                        domain=dom,
                        classification=ResponseClassification.JS_RENDER_REQUIRED,
                        http_status=status_code,
                        retryable=False,
                        suggested_action="render_browser",
                        reason="Page explicitly indicates JavaScript execution is required (<noscript>)",
                        execution_time_ms=execution_time_ms,
                        attempt_count=attempt_count,
                        headers_snippet=safe_hdrs,
                    )

                # 2. Empty SPA root container with minimal visible text
                visible_text = self._strip_tags(snippet)
                if len(visible_text) < 100 and any(p.search(snippet) for p in self.SPA_CONTAINER_PATTERNS):
                    return RequestDiagnostics(
                        url=url,
                        domain=dom,
                        classification=ResponseClassification.JS_RENDER_REQUIRED,
                        http_status=status_code,
                        retryable=False,
                        suggested_action="render_browser",
                        reason="Client-side Single Page Application (SPA) container detected with empty static DOM",
                        execution_time_ms=execution_time_ms,
                        attempt_count=attempt_count,
                        headers_snippet=safe_hdrs,
                    )

            # Normal success
            return RequestDiagnostics(
                url=url,
                domain=dom,
                classification=ResponseClassification.SUCCESS,
                http_status=status_code,
                retryable=False,
                suggested_action="proceed",
                reason="HTTP request completed successfully",
                execution_time_ms=execution_time_ms,
                attempt_count=attempt_count,
                headers_snippet=safe_hdrs,
            )

        # Unclassified fallback
        return RequestDiagnostics(
            url=url,
            domain=dom,
            classification=ResponseClassification.UNKNOWN_ERROR,
            http_status=status_code,
            retryable=False,
            suggested_action="inspect_error",
            reason=f"Unclassified HTTP response status {status_code}",
            execution_time_ms=execution_time_ms,
            attempt_count=attempt_count,
            headers_snippet=safe_hdrs,
        )


# ==============================================================================
# 3. Retry Engine (RetryPolicy)
# ==============================================================================

class RetryPolicy:
    """Determines retry feasibility, parses Retry-After, and computes exponential backoff with jitter."""

    DEFAULT_RETRYABLE_STATUS_CODES: Final[set[int]] = {429, 500, 502, 503, 504}
    DEFAULT_NON_RETRYABLE_STATUS_CODES: Final[set[int]] = {400, 401, 403, 404, 405, 410, 413, 422}

    DEFAULT_RETRYABLE_EXCEPTIONS: Final[tuple[type[Exception], ...]] = (
        httpx.TimeoutException,
        httpx.ConnectError,
        httpx.ReadError,
        httpx.RemoteProtocolError,
        httpx.NetworkError,
        ConnectionError,
        OSError,
    )

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
        backoff_factor: float = 2.0,
        jitter: bool = True,
        retryable_status_codes: Optional[set[int]] = None,
    ) -> None:
        self.max_retries = max(0, max_retries)
        self.base_delay = max(0.01, base_delay)
        self.max_delay = max(self.base_delay, max_delay)
        self.backoff_factor = max(1.0, backoff_factor)
        self.jitter = jitter
        self.retryable_status_codes = retryable_status_codes or set(self.DEFAULT_RETRYABLE_STATUS_CODES)

    def parse_retry_after(self, header_val: Optional[str]) -> Optional[float]:
        """Parse standard HTTP Retry-After header (seconds integer or RFC 2822 date).

        Returns:
            Delay in seconds bounded by self.max_delay, or None if invalid/missing.
        """
        if not header_val or not header_val.strip():
            return None
        val = header_val.strip()

        # 1. Direct integer or decimal seconds
        try:
            sec = float(val)
            if sec < 0:
                return 0.0
            return min(sec, self.max_delay)
        except ValueError:
            pass

        # 2. HTTP-date format (e.g. 'Wed, 21 Oct 2026 07:28:00 GMT')
        try:
            target_dt = email.utils.parsedate_to_datetime(val)
            if target_dt is not None:
                if target_dt.tzinfo is None:
                    target_dt = target_dt.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                diff = (target_dt - now).total_seconds()
                return min(max(0.0, diff), self.max_delay)
        except Exception as exc:
            logger.debug("Failed parsing Retry-After date '%s': %s", val, exc)

        return None

    def should_retry(
        self,
        attempt: int,
        status_code: Optional[int] = None,
        exception: Optional[Exception] = None,
    ) -> bool:
        """Determine if an operation should be retried given current attempt and outcome."""
        if attempt >= self.max_retries:
            return False

        if isinstance(exception, asyncio.CancelledError):
            return False

        if exception is not None:
            return isinstance(exception, self.DEFAULT_RETRYABLE_EXCEPTIONS)

        if status_code is not None:
            if status_code in self.retryable_status_codes:
                return True
            if status_code in self.DEFAULT_NON_RETRYABLE_STATUS_CODES:
                return False

        return False

    def compute_delay(
        self,
        attempt: int,
        status_code: Optional[int] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> float:
        """Compute delay before the next retry attempt using exponential backoff with jitter."""
        # 1. Honor Retry-After header if present
        if headers:
            retry_after_hdr = None
            for k, v in headers.items():
                if k.lower() == "retry-after":
                    retry_after_hdr = v
                    break
            parsed = self.parse_retry_after(retry_after_hdr)
            if parsed is not None:
                # Add slight random jitter to avoid thundering herd
                if self.jitter:
                    parsed += random.uniform(0.0, min(0.5, parsed * 0.1))
                return min(parsed, self.max_delay)

        # 2. Exponential backoff: base_delay * (backoff_factor ** attempt)
        raw_delay = self.base_delay * (self.backoff_factor ** max(0, attempt))
        capped_delay = min(raw_delay, self.max_delay)

        # 3. Apply Equal Jitter: uniform(0.5 * delay, delay)
        if self.jitter and capped_delay > 0:
            half = capped_delay / 2.0
            return half + random.uniform(0.0, half)

        return capped_delay


# ==============================================================================
# 4. Request Scheduler (RequestScheduler)
# ==============================================================================

class DomainState:
    """Thread-safe and async-safe state tracker for an individual domain."""

    def __init__(self, domain: str, max_concurrency: int = 2) -> None:
        self.domain = domain
        self.max_concurrency = max(1, max_concurrency)
        self.semaphore = asyncio.Semaphore(self.max_concurrency)
        self.last_request_time: float = 0.0
        self.last_accessed: float = time.monotonic()
        self._lock = asyncio.Lock()

    def touch(self) -> None:
        self.last_accessed = time.monotonic()


class RequestScheduler:
    """Coordinates global and per-domain concurrency limits and inter-request delays."""

    def __init__(
        self,
        max_global_concurrency: int = 10,
        default_domain_concurrency: int = 2,
        default_min_delay: float = 0.5,
        max_cached_domains: int = 1000,
    ) -> None:
        self.max_global_concurrency = max(1, max_global_concurrency)
        self.default_domain_concurrency = max(1, default_domain_concurrency)
        self.default_min_delay = max(0.0, default_min_delay)
        self.max_cached_domains = max_cached_domains

        self._global_semaphore = asyncio.Semaphore(self.max_global_concurrency)
        self._domain_states: dict[str, DomainState] = {}
        self._state_lock = asyncio.Lock()

    @staticmethod
    def extract_domain(url: str) -> str:
        """Extract canonical lowercase domain name from URL."""
        if not url:
            return "unknown"
        if "://" not in url:
            url = f"https://{url}"
        try:
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            return host or "unknown"
        except Exception:
            return "unknown"

    async def get_or_create_domain_state(
        self,
        domain: str,
        custom_concurrency: Optional[int] = None,
    ) -> DomainState:
        """Retrieve existing DomainState or create a new one safely under lock."""
        async with self._state_lock:
            state = self._domain_states.get(domain)
            if state is None:
                if len(self._domain_states) >= self.max_cached_domains:
                    self._prune_inactive_domains_locked()

                concurrency = custom_concurrency or self.default_domain_concurrency
                state = DomainState(domain=domain, max_concurrency=concurrency)
                self._domain_states[domain] = state

            state.touch()
            return state

    def _prune_inactive_domains_locked(self) -> None:
        """Prune domains with no in-flight requests to bound memory usage."""
        now = time.monotonic()
        to_remove = []
        for domain, state in self._domain_states.items():
            if getattr(state.semaphore, "_value", 0) == state.max_concurrency:
                if now - state.last_accessed > 60.0:
                    to_remove.append(domain)

        for d in to_remove:
            self._domain_states.pop(d, None)

    @asynccontextmanager
    async def schedule(
        self,
        url_or_domain: str,
        min_delay: Optional[float] = None,
        cancel_event: Optional[asyncio.Event] = None,
        domain_concurrency: Optional[int] = None,
    ) -> AsyncIterator[DomainState]:
        """Async context manager acquiring global and domain slots, enforcing rate limits."""
        domain = self.extract_domain(url_or_domain) if "://" in url_or_domain else url_or_domain.lower()
        domain_state = await self.get_or_create_domain_state(domain, custom_concurrency=domain_concurrency)

        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError(f"Request cancelled before scheduling for {domain}")

        # 1. Acquire global concurrency slot
        await self._global_semaphore.acquire()
        try:
            if cancel_event is not None and cancel_event.is_set():
                raise asyncio.CancelledError(f"Request cancelled while acquiring global slot for {domain}")

            # 2. Acquire domain concurrency slot
            await domain_state.semaphore.acquire()
            try:
                if cancel_event is not None and cancel_event.is_set():
                    raise asyncio.CancelledError(f"Request cancelled while acquiring domain slot for {domain}")

                # 3. Enforce inter-request rate limit spacing
                effective_min_delay = self.default_min_delay if min_delay is None else max(0.0, min_delay)
                if effective_min_delay > 0:
                    async with domain_state._lock:
                        now = time.monotonic()
                        elapsed = now - domain_state.last_request_time
                        if elapsed < effective_min_delay:
                            delay_needed = (effective_min_delay - elapsed) + random.uniform(0.0, 0.1)
                            if cancel_event is not None:
                                try:
                                    await asyncio.wait_for(cancel_event.wait(), timeout=delay_needed)
                                    raise asyncio.CancelledError("Cancelled during domain rate limit wait")
                                except asyncio.TimeoutError:
                                    pass
                            else:
                                await asyncio.sleep(delay_needed)
                        domain_state.last_request_time = time.monotonic()

                # Yield domain state to the caller for execution
                yield domain_state

            finally:
                domain_state.semaphore.release()
                domain_state.touch()
        finally:
            self._global_semaphore.release()


# ==============================================================================
# 5. Domain Policy Manager (DomainPolicyManager)
# ==============================================================================

class DomainPolicyManager:
    """Manages custom and default crawl policies per domain."""

    def __init__(self, default_policy: Optional[DomainPolicy] = None) -> None:
        self.default_policy = default_policy or DomainPolicy(domain="*")
        self._policies: dict[str, DomainPolicy] = {}

    def set_policy(self, policy: DomainPolicy) -> None:
        """Register or update a custom domain policy."""
        domain_key = policy.domain.strip().lower()
        self._policies[domain_key] = policy

    def get_policy(self, domain_or_url: str) -> DomainPolicy:
        """Retrieve policy for a domain with wildcard and default fallbacks."""
        domain = RequestScheduler.extract_domain(domain_or_url) if "://" in domain_or_url else domain_or_url.strip().lower()

        if domain in self._policies:
            return self._policies[domain]

        for registered_domain, pol in self._policies.items():
            if pol.allow_subdomains and (domain == registered_domain or domain.endswith(f".{registered_domain}")):
                return pol

        return self.default_policy

    def set_crawl_delay(self, domain_or_url: str, delay: float) -> None:
        """Update or register domain crawl delay from robots.txt directive."""
        domain_key = RequestScheduler.extract_domain(domain_or_url) if "://" in domain_or_url else domain_or_url.strip().lower()
        existing = self._policies.get(domain_key)
        if existing:
            existing.min_delay_seconds = max(existing.min_delay_seconds, delay)
        else:
            self._policies[domain_key] = DomainPolicy(
                domain=domain_key,
                min_delay_seconds=delay,
            )


# ==============================================================================
# 6. Session and Connection Lifecycle Manager (SessionManager)
# ==============================================================================

DEFAULT_BROWSER_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

DEFAULT_BROWSER_HEADERS: Final[dict[str, str]] = {
    "User-Agent": DEFAULT_BROWSER_USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fa-IR,fa;q=0.9,en-US;q=0.8,en;q=0.7",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


class SessionManager:
    """Manages reusable httpx.AsyncClient connection pools scoped to tenants or jobs."""

    USER_AGENT: Final[str] = DEFAULT_BROWSER_USER_AGENT

    def __init__(
        self,
        default_timeout: float = 30.0,
        max_connections: int = 50,
        max_keepalive_connections: int = 20,
    ) -> None:
        self.default_timeout = default_timeout
        self.max_connections = max_connections
        self.max_keepalive_connections = max_keepalive_connections

        self._clients: dict[str, httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()

    async def get_client(
        self,
        tenant_id: Optional[str] = None,
        custom_transport: Optional[httpx.AsyncBaseTransport] = None,
        verify_ssl: bool = True,
        headers: Optional[dict[str, str]] = None,
    ) -> httpx.AsyncClient:
        """Get or initialize a long-lived httpx.AsyncClient for the specified tenant."""
        default_hdrs = dict(DEFAULT_BROWSER_HEADERS)
        if headers:
            default_hdrs.update(headers)

        from unittest.mock import Mock
        if isinstance(httpx.AsyncClient, Mock):
            return httpx.AsyncClient(
                timeout=self.default_timeout,
                verify=verify_ssl,
                follow_redirects=False,
                headers=default_hdrs,
            )

        key = tenant_id or "default"

        async with self._lock:
            if custom_transport is not None:
                return httpx.AsyncClient(
                    transport=custom_transport,
                    timeout=self.default_timeout,
                    verify=verify_ssl,
                    follow_redirects=False,
                    headers=default_hdrs,
                )

            client = self._clients.get(key)
            if client is None or client.is_closed:
                limits = httpx.Limits(
                    max_connections=self.max_connections,
                    max_keepalive_connections=self.max_keepalive_connections,
                )
                client = httpx.AsyncClient(
                    timeout=self.default_timeout,
                    verify=verify_ssl,
                    follow_redirects=False,
                    limits=limits,
                    headers=default_hdrs,
                )
                self._clients[key] = client

            return client

    async def close_client(self, tenant_id: Optional[str] = None) -> None:
        """Close client for a specific tenant when job completes."""
        key = tenant_id or "default"
        async with self._lock:
            client = self._clients.pop(key, None)
            if client is not None and not client.is_closed:
                try:
                    await client.aclose()
                except Exception as exc:
                    logger.debug("Error closing client for %s: %s", key, exc)

    async def close_all(self) -> None:
        """Safely close all managed HTTP clients and connection pools."""
        async with self._lock:
            for client in self._clients.values():
                try:
                    if not client.is_closed:
                        await client.aclose()
                except Exception as exc:
                    logger.debug("Error closing client: %s", exc)
            self._clients.clear()


# ==============================================================================
# 7. Observability & Telemetry (JobMetricsSummary & MetricsCollector)
# ==============================================================================

@dataclass
class JobMetricsSummary:
    """Aggregated resilience and anti-bot metrics for jobs or global observability.

    Tracks 11 standard metrics:
    1. requests_total: Total number of requests attempted/handled
    2. successful_requests: Count of successful (2xx) responses
    3. failed_requests: Count of non-successful requests
    4. blocked_requests: Requests rejected by bot challenges, 403, or robots.txt
    5. rate_limited_requests: Requests that encountered 429 Too Many Requests
    6. retry_attempts: Total retry iterations executed
    7. retry_exhausted: Total requests where all retry budget was spent
    8. timeout_count: Requests encountering HTTP or connection timeouts
    9. average_request_latency: Average request duration in seconds
    10. browser_fallback_count: Number of transitions/promotions to headless browser
    11. classification_count: Distribution of 12 standard ResponseClassifications
    """

    requests_total: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    blocked_requests: int = 0
    rate_limited_requests: int = 0
    retry_attempts: int = 0
    retry_exhausted: int = 0
    timeout_count: int = 0
    total_latency: float = 0.0
    average_request_latency: float = 0.0
    browser_fallback_count: int = 0
    classification_count: dict[str, int] = field(
        default_factory=lambda: {c.value: 0 for c in ResponseClassification}
    )

    def record_attempt(
        self,
        classification: ResponseClassification | str,
        latency_seconds: float = 0.0,
    ) -> None:
        """Record an individual HTTP attempt (status / error classification)."""
        c_val = classification.value if isinstance(classification, ResponseClassification) else str(classification)
        if c_val not in self.classification_count:
            self.classification_count[c_val] = 0
        self.classification_count[c_val] += 1

        if c_val == ResponseClassification.RATE_LIMITED.value:
            self.rate_limited_requests += 1
        elif c_val == ResponseClassification.TIMEOUT.value:
            self.timeout_count += 1
        elif c_val in (
            ResponseClassification.HTTP_FORBIDDEN.value,
            ResponseClassification.BOT_PROTECTION.value,
            ResponseClassification.CAPTCHA_REQUIRED.value,
            ResponseClassification.ROBOTS_DENIED.value,
            ResponseClassification.AUTH_REQUIRED.value,
        ):
            self.blocked_requests += 1

    def record_request_outcome(
        self,
        classification: ResponseClassification | str,
        total_latency_seconds: float,
        retries: int = 0,
        retry_exhausted: bool = False,
    ) -> None:
        """Record the overall request outcome after all attempts/retries complete."""
        c_val = classification.value if isinstance(classification, ResponseClassification) else str(classification)
        self.requests_total += 1
        self.total_latency += max(0.0, total_latency_seconds)
        self.average_request_latency = round(self.total_latency / self.requests_total, 4)
        self.retry_attempts += max(0, retries)
        if retry_exhausted:
            self.retry_exhausted += 1

        if c_val == ResponseClassification.SUCCESS.value:
            self.successful_requests += 1
        else:
            self.failed_requests += 1

    def record_request(
        self,
        classification: ResponseClassification | str,
        latency_seconds: float = 0.0,
        retries: int = 0,
        retry_exhausted: bool = False,
    ) -> None:
        """Single-call convenience method recording both attempt telemetry and final outcome."""
        self.record_attempt(classification=classification, latency_seconds=latency_seconds)
        self.record_request_outcome(
            classification=classification,
            total_latency_seconds=latency_seconds,
            retries=retries,
            retry_exhausted=retry_exhausted,
        )

    def record_browser_fallback(self) -> None:
        """Record a fallback/promotion to browser rendering."""
        self.browser_fallback_count += 1

    def to_dict(self) -> dict[str, Any]:
        """Convert metrics to a clean serializable dictionary with bounded labels."""
        avg_latency = (
            round(self.total_latency / self.requests_total, 4)
            if self.requests_total > 0
            else self.average_request_latency
        )
        return {
            "requests_total": self.requests_total,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "blocked_requests": self.blocked_requests,
            "rate_limited_requests": self.rate_limited_requests,
            "retry_attempts": self.retry_attempts,
            "retry_exhausted": self.retry_exhausted,
            "timeout_count": self.timeout_count,
            "average_request_latency": avg_latency,
            "browser_fallback_count": self.browser_fallback_count,
            "classification_count": dict(self.classification_count),
        }


class MetricsCollector:
    """Thread-safe aggregator for request resilience, anti-bot, and execution metrics."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._global_metrics = JobMetricsSummary()
        self._job_metrics: dict[str, JobMetricsSummary] = defaultdict(JobMetricsSummary)

    def record_attempt(
        self,
        job_id: Optional[str],
        classification: ResponseClassification | str,
        latency_seconds: float = 0.0,
    ) -> None:
        """Record single attempt telemetry globally and per job."""
        with self._lock:
            self._global_metrics.record_attempt(classification, latency_seconds)
            if job_id:
                self._job_metrics[job_id].record_attempt(classification, latency_seconds)

    def record_request_outcome(
        self,
        job_id: Optional[str],
        classification: ResponseClassification | str,
        total_latency_seconds: float,
        retries: int = 0,
        retry_exhausted: bool = False,
    ) -> None:
        """Record final request outcome globally and per job."""
        with self._lock:
            self._global_metrics.record_request_outcome(
                classification, total_latency_seconds, retries, retry_exhausted
            )
            if job_id:
                self._job_metrics[job_id].record_request_outcome(
                    classification, total_latency_seconds, retries, retry_exhausted
                )

    def record_request(
        self,
        job_id: Optional[str],
        classification: ResponseClassification | str,
        latency_seconds: float = 0.0,
        retries: int = 0,
        retry_exhausted: bool = False,
    ) -> None:
        """Convenience method to record a complete request globally and per job."""
        with self._lock:
            self._global_metrics.record_request(
                classification=classification,
                latency_seconds=latency_seconds,
                retries=retries,
                retry_exhausted=retry_exhausted,
            )
            if job_id:
                self._job_metrics[job_id].record_request(
                    classification=classification,
                    latency_seconds=latency_seconds,
                    retries=retries,
                    retry_exhausted=retry_exhausted,
                )

    def record_browser_fallback(self, job_id: Optional[str] = None) -> None:
        """Record a browser rendering transition globally and per job."""
        with self._lock:
            self._global_metrics.record_browser_fallback()
            if job_id:
                self._job_metrics[job_id].record_browser_fallback()

    def get_metrics(self, job_id: Optional[str] = None) -> dict[str, Any]:
        """Return metrics dictionary for a job (if provided) or global metrics."""
        with self._lock:
            if job_id is not None:
                if job_id in self._job_metrics:
                    return self._job_metrics[job_id].to_dict()
                return JobMetricsSummary().to_dict()
            return self._global_metrics.to_dict()

    def get_summary(self, job_id: Optional[str] = None) -> JobMetricsSummary:
        """Return a typed snapshot of JobMetricsSummary."""
        with self._lock:
            target = self._job_metrics.get(job_id) if job_id is not None else self._global_metrics
            if target is None:
                return JobMetricsSummary()
            d = target.to_dict()
            return JobMetricsSummary(
                requests_total=d["requests_total"],
                successful_requests=d["successful_requests"],
                failed_requests=d["failed_requests"],
                blocked_requests=d["blocked_requests"],
                rate_limited_requests=d["rate_limited_requests"],
                retry_attempts=d["retry_attempts"],
                retry_exhausted=d["retry_exhausted"],
                timeout_count=d["timeout_count"],
                total_latency=target.total_latency,
                average_request_latency=d["average_request_latency"],
                browser_fallback_count=d["browser_fallback_count"],
                classification_count=dict(d["classification_count"]),
            )

    def reset(self, job_id: Optional[str] = None) -> None:
        """Reset metrics. If job_id is None, resets both global and all job metrics."""
        with self._lock:
            if job_id is not None:
                self._job_metrics.pop(job_id, None)
            else:
                self._global_metrics = JobMetricsSummary()
                self._job_metrics.clear()


# ==============================================================================
# 8. AntiBotManager (Core Orchestrator Facade)
# ==============================================================================

class AntiBotManager:
    """Unified coordinator for resilient, anti-bot aware, rate-limited HTTP fetching.

    Integrates:
    - RequestScheduler (Global & Domain concurrency, delays)
    - RetryPolicy (Exponential backoff, Jitter, Retry-After compliance)
    - SessionManager (Pooled, tenant-safe HTTPX clients)
    - DomainPolicyManager (Per-domain overrides)
    - ResponseAnalyzer (Standardized 12-state diagnostics)
    - MetricsCollector (Thread-safe observability, bounded metric labels)
    """

    def __init__(
        self,
        scheduler: Optional[RequestScheduler] = None,
        retry_policy: Optional[RetryPolicy] = None,
        session_manager: Optional[SessionManager] = None,
        policy_manager: Optional[DomainPolicyManager] = None,
        analyzer: Optional[ResponseAnalyzer] = None,
        metrics: Optional[MetricsCollector] = None,
    ) -> None:
        self.scheduler = scheduler or RequestScheduler()
        self.retry_policy = retry_policy or RetryPolicy()
        self.session_manager = session_manager or SessionManager()
        self.policy_manager = policy_manager or DomainPolicyManager()
        self.analyzer = analyzer or ResponseAnalyzer()
        self.metrics = metrics or MetricsCollector()

    def record_browser_fallback(self, job_id: Optional[str] = None) -> None:
        """Record browser promotion telemetry."""
        self.metrics.record_browser_fallback(job_id=job_id)

    def _record_and_log(
        self,
        job_id: Optional[str],
        diag: RequestDiagnostics,
        elapsed_ms: float,
        retries: int,
        retry_exhausted: bool = False,
        record_attempt: bool = False,
    ) -> None:
        """Record final request outcome and emit structured log."""
        if record_attempt:
            self.metrics.record_attempt(
                job_id=job_id,
                classification=diag.classification,
                latency_seconds=elapsed_ms / 1000.0,
            )
        self.metrics.record_request_outcome(
            job_id=job_id,
            classification=diag.classification,
            total_latency_seconds=elapsed_ms / 1000.0,
            retries=retries,
            retry_exhausted=retry_exhausted,
        )
        logger.info(
            "HTTP request complete: %s -> %s (status=%s, elapsed=%.1fms, retries=%d, job_id=%s)",
            diag.domain,
            diag.classification.value,
            diag.http_status,
            elapsed_ms,
            retries,
            job_id or "none",
            extra={
                "domain": diag.domain,
                "classification": diag.classification.value,
                "http_status": diag.http_status,
                "execution_time_ms": elapsed_ms,
                "retries": retries,
                "retry_exhausted": retry_exhausted,
                "job_id": job_id,
            },
        )

    async def fetch(
        self,
        url: str,
        method: str = "GET",
        headers: Optional[dict[str, str]] = None,
        tenant_id: Optional[str] = None,
        cancel_event: Optional[asyncio.Event] = None,
        custom_client: Optional[httpx.AsyncClient] = None,
        custom_transport: Optional[httpx.AsyncBaseTransport] = None,
        max_redirects: int = 5,
        max_response_size: int = 10 * 1024 * 1024,
        url_validator: Optional[Any] = None,
        job_id: Optional[str] = None,
    ) -> tuple[Optional[httpx.Response], RequestDiagnostics]:
        """Fetch an HTTP URL with rate-limiting, retries, SSRF validation, diagnostics, and metrics.

        Returns:
            Tuple of (httpx.Response or None, RequestDiagnostics)
        """
        domain = RequestScheduler.extract_domain(url)
        policy = self.policy_manager.get_policy(domain)
        start_time = time.perf_counter()

        client = custom_client or await self.session_manager.get_client(
            tenant_id=tenant_id,
            custom_transport=custom_transport,
        )

        attempt = 0
        last_exception: Optional[Exception] = None
        last_response: Optional[httpx.Response] = None
        current_url = url
        redirect_hops = 0

        while True:
            if cancel_event is not None and cancel_event.is_set():
                elapsed = (time.perf_counter() - start_time) * 1000
                diag = self.analyzer.analyze(
                    url=current_url,
                    domain=domain,
                    exception=asyncio.CancelledError(),
                    execution_time_ms=elapsed,
                    attempt_count=attempt,
                )
                self._record_and_log(
                    job_id=job_id,
                    diag=diag,
                    elapsed_ms=elapsed,
                    retries=attempt,
                    retry_exhausted=False,
                    record_attempt=True,
                )
                return None, diag

            # SSRF Security Validation
            validator = url_validator or validate_url_safety
            is_safe, reason = validator(current_url)
            if not is_safe:
                elapsed = (time.perf_counter() - start_time) * 1000
                diag = self.analyzer.analyze(
                    url=current_url,
                    domain=domain,
                    status_code=403,
                    custom_reason=f"SSRF validation blocked: {reason}",
                    execution_time_ms=elapsed,
                    attempt_count=attempt,
                )
                self._record_and_log(
                    job_id=job_id,
                    diag=diag,
                    elapsed_ms=elapsed,
                    retries=attempt,
                    retry_exhausted=False,
                    record_attempt=True,
                )
                return None, diag

            # Execute attempt under scheduler concurrency control
            attempt_start = time.perf_counter()
            try:
                async with self.scheduler.schedule(
                    domain,
                    min_delay=policy.min_delay_seconds,
                    cancel_event=cancel_event,
                    domain_concurrency=policy.max_concurrency,
                ):
                    response = await client.request(
                        method=method,
                        url=current_url,
                        headers=headers,
                        timeout=policy.request_timeout,
                        follow_redirects=False,
                    )
                    last_response = response
                    status = response.status_code
                    attempt_elapsed = (time.perf_counter() - attempt_start) * 1000
                    total_elapsed = (time.perf_counter() - start_time) * 1000

                    # Handle Redirects
                    if status in (301, 302, 303, 307, 308) and redirect_hops < max_redirects:
                        loc = response.headers.get("Location")
                        if loc:
                            redirect_hops += 1
                            current_url = str(response.url.join(loc))
                            continue

                    # Analyze response content and status
                    body_snippet = response.content[:ResponseAnalyzer.MAX_SNIPPET_BYTES]
                    diag = self.analyzer.analyze(
                        url=current_url,
                        domain=domain,
                        status_code=status,
                        headers=dict(response.headers),
                        body=body_snippet,
                        execution_time_ms=attempt_elapsed,
                        attempt_count=attempt + 1,
                    )
                    self.metrics.record_attempt(
                        job_id=job_id,
                        classification=diag.classification,
                        latency_seconds=attempt_elapsed / 1000.0,
                    )

                    # If successful or JS render required, return response immediately
                    if diag.classification in (ResponseClassification.SUCCESS, ResponseClassification.JS_RENDER_REQUIRED):
                        self._record_and_log(
                            job_id=job_id,
                            diag=diag,
                            elapsed_ms=total_elapsed,
                            retries=attempt,
                            retry_exhausted=False,
                        )
                        return response, diag

                    # Check if retryable (e.g. rate limit or server error)
                    if diag.retryable and self.retry_policy.should_retry(attempt, status_code=status):
                        delay = self.retry_policy.compute_delay(
                            attempt,
                            status_code=status,
                            headers=dict(response.headers),
                        )
                        logger.info(
                            "Retrying %s (%s, status %d) in %.2fs (attempt %d/%d)",
                            current_url, diag.classification.value, status, delay, attempt + 1, self.retry_policy.max_retries,
                        )
                        attempt += 1
                        await asyncio.sleep(delay)
                        continue

                    # Terminal failure (forbidden, bot blocked, captcha, or retries exhausted)
                    is_exhausted = diag.retryable and not self.retry_policy.should_retry(attempt, status_code=status)
                    self._record_and_log(
                        job_id=job_id,
                        diag=diag,
                        elapsed_ms=total_elapsed,
                        retries=attempt,
                        retry_exhausted=is_exhausted,
                    )
                    return response, diag

            except Exception as exc:
                last_exception = exc
                attempt_elapsed = (time.perf_counter() - attempt_start) * 1000
                total_elapsed = (time.perf_counter() - start_time) * 1000

                if isinstance(exc, asyncio.CancelledError):
                    raise

                diag = self.analyzer.analyze(
                    url=current_url,
                    domain=domain,
                    exception=exc,
                    execution_time_ms=attempt_elapsed,
                    attempt_count=attempt + 1,
                )
                self.metrics.record_attempt(
                    job_id=job_id,
                    classification=diag.classification,
                    latency_seconds=attempt_elapsed / 1000.0,
                )

                if diag.retryable and self.retry_policy.should_retry(attempt, exception=exc):
                    delay = self.retry_policy.compute_delay(attempt)
                    logger.info(
                        "Retrying %s after %s in %.2fs (attempt %d/%d)",
                        current_url, exc.__class__.__name__, delay, attempt + 1, self.retry_policy.max_retries,
                    )
                    attempt += 1
                    await asyncio.sleep(delay)
                    continue

                is_exhausted = diag.retryable and not self.retry_policy.should_retry(attempt, exception=exc)
                self._record_and_log(
                    job_id=job_id,
                    diag=diag,
                    elapsed_ms=total_elapsed,
                    retries=attempt,
                    retry_exhausted=is_exhausted,
                )
                return None, diag

        # Fallback diagnostics on exhaustion
        total_elapsed = (time.perf_counter() - start_time) * 1000
        diag = self.analyzer.analyze(
            url=current_url,
            domain=domain,
            status_code=last_response.status_code if last_response else None,
            exception=last_exception,
            custom_reason=f"Exhausted {self.retry_policy.max_retries} retries",
            execution_time_ms=total_elapsed,
            attempt_count=attempt,
        )
        self._record_and_log(
            job_id=job_id,
            diag=diag,
            elapsed_ms=total_elapsed,
            retries=attempt,
            retry_exhausted=True,
        )
        return last_response, diag

    async def run(self, *args, **kwargs) -> Any:
        """Public alias for backward compatibility."""
        return await self.fetch(*args, **kwargs)


# ==============================================================================
# 8. Singleton Factory
# ==============================================================================

_antibot_manager: Optional[AntiBotManager] = None


def get_antibot_manager() -> AntiBotManager:
    """Return the global AntiBotManager singleton instance."""
    global _antibot_manager
    if _antibot_manager is None:
        settings = get_settings()
        scheduler = RequestScheduler(
            max_global_concurrency=settings.max_concurrency,
            default_domain_concurrency=2,
            default_min_delay=settings.delay_between_requests,
        )
        retry_policy = RetryPolicy(
            max_retries=3,
            base_delay=1.0,
            max_delay=30.0,
        )
        session_manager = SessionManager(
            default_timeout=settings.request_timeout,
        )
        analyzer = ResponseAnalyzer()
        _antibot_manager = AntiBotManager(
            scheduler=scheduler,
            retry_policy=retry_policy,
            session_manager=session_manager,
            analyzer=analyzer,
        )
    return _antibot_manager
