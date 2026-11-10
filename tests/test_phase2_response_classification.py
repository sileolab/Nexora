"""Phase 2 Unit and Integration Tests:
12-State Response Classification, Deep Signal Analysis, Anti-Bot & CAPTCHA Detection,
JS Rendering Triggers, and Sensitive Header Sanitization.
"""

from __future__ import annotations

import asyncio
import httpx
import pytest

from app.services.anti_bot import (
    AntiBotManager,
    RequestDiagnostics,
    ResponseAnalyzer,
    ResponseClassification,
    sanitize_headers,
)


@pytest.fixture
def analyzer() -> ResponseAnalyzer:
    return ResponseAnalyzer()


# ==============================================================================
# 1. Standard Success vs False 200 Tests
# ==============================================================================

def test_classify_normal_success_200(analyzer: ResponseAnalyzer):
    """Standard 200 response with textual content must classify as SUCCESS."""
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>Documentation Guide</title></head>
    <body>
        <h1>Crawlbot Documentation</h1>
        <p>This is a complete comprehensive user guide detailing how the web crawler functions
        and parses HTML documents for downstream vector embedding.</p>
    </body>
    </html>
    """
    diag = analyzer.analyze("https://example.com/docs", status_code=200, body=html)

    assert diag.classification == ResponseClassification.SUCCESS
    assert diag.http_status == 200
    assert diag.retryable is False
    assert diag.suggested_action == "proceed"


def test_classify_normal_page_with_scripts_is_success(analyzer: ResponseAnalyzer):
    """Rich static page with ordinary scripts must classify as SUCCESS, NOT JS_RENDER_REQUIRED."""
    html = """
    <html>
    <head>
        <title>Tech Blog</title>
        <script src="https://cdn.example.com/analytics.js"></script>
    </head>
    <body>
        <h1>Deep Learning Innovations</h1>
        <p>Artificial intelligence and neural networks are rapidly advancing. Large language models
        have transformed natural language understanding and automated coding assistants.</p>
        <script>console.log("Track event");</script>
    </body>
    </html>
    """
    diag = analyzer.analyze("https://example.com/blog", status_code=200, body=html)

    assert diag.classification == ResponseClassification.SUCCESS
    assert diag.suggested_action == "proceed"


# ==============================================================================
# 2. HTTP 403 Forbidden vs Bot Protection & WAF Tests
# ==============================================================================

def test_classify_standard_http_403_forbidden(analyzer: ResponseAnalyzer):
    """Standard HTTP 403 without bot protection markers must classify as HTTP_FORBIDDEN."""
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>403 Forbidden</title></head>
    <body>
        <h1>403 Forbidden</h1>
        <p>You don't have permission to access /private/ on this server.</p>
        <hr><address>Apache/2.4.41 (Ubuntu) Server at example.com Port 443</address>
    </body>
    </html>
    """
    diag = analyzer.analyze("https://example.com/private", status_code=403, body=html)

    assert diag.classification == ResponseClassification.HTTP_FORBIDDEN
    assert diag.http_status == 403
    assert diag.retryable is False
    assert diag.suggested_action == "skip_forbidden"


def test_classify_bot_protection_cloudflare(analyzer: ResponseAnalyzer):
    """Cloudflare challenge page or headers must classify as BOT_PROTECTION."""
    html = """
    <html>
    <head><title>Attention Required! | Cloudflare</title></head>
    <body>
        <h2>Checking your browser before accessing example.com.</h2>
        <div id="cf-browser-verification"></div>
    </body>
    </html>
    """
    diag = analyzer.analyze(
        "https://example.com/data",
        status_code=403,
        headers={"Server": "cloudflare", "cf-mitigated": "challenge"},
        body=html,
    )

    assert diag.classification == ResponseClassification.BOT_PROTECTION
    assert diag.retryable is False
    assert diag.suggested_action == "respect_block"


def test_classify_bot_protection_datadome_and_perimeterx(analyzer: ResponseAnalyzer):
    """DataDome and PerimeterX automation block markers must classify as BOT_PROTECTION."""
    html = """
    <html>
    <head><title>Access Denied</title></head>
    <body>
        <p>Access to this page has been denied because we believe you are using automation tools to browse the website.</p>
        <p>Protected by DataDome</p>
    </body>
    </html>
    """
    diag = analyzer.analyze(
        "https://example.com/catalog",
        status_code=403,
        headers={"x-datadome": "protected"},
        body=html,
    )

    assert diag.classification == ResponseClassification.BOT_PROTECTION
    assert diag.suggested_action == "respect_block"


# ==============================================================================
# 3. Explicit CAPTCHA Detection Tests
# ==============================================================================

def test_classify_captcha_required_recaptcha(analyzer: ResponseAnalyzer):
    """Pages demanding Google reCAPTCHA resolution must classify as CAPTCHA_REQUIRED."""
    html = """
    <html>
    <body>
        <h1>Security Check</h1>
        <p>Please verify you are human to continue.</p>
        <div class="g-recaptcha" data-sitekey="6Lce123..."></div>
        <script src="https://www.google.com/recaptcha/api.js"></script>
    </body>
    </html>
    """
    diag = analyzer.analyze("https://example.com/verify", status_code=200, body=html)

    assert diag.classification == ResponseClassification.CAPTCHA_REQUIRED
    assert diag.retryable is False
    assert diag.suggested_action == "captcha_blocked"


def test_classify_captcha_required_turnstile_and_hcaptcha(analyzer: ResponseAnalyzer):
    """Cloudflare Turnstile or hCaptcha widgets must classify as CAPTCHA_REQUIRED."""
    html = """
    <html>
    <body>
        <h2>Complete the security check to proceed</h2>
        <div class="cf-turnstile" data-sitekey="0x4AAAAAA..."></div>
        <script src="https://challenges.cloudflare.com/turnstile/v0/api.js"></script>
    </body>
    </html>
    """
    diag = analyzer.analyze("https://example.com/checkout", status_code=403, body=html)

    assert diag.classification == ResponseClassification.CAPTCHA_REQUIRED
    assert diag.suggested_action == "captcha_blocked"


# ==============================================================================
# 4. Rate Limiting Tests
# ==============================================================================

def test_classify_rate_limited_429(analyzer: ResponseAnalyzer):
    """HTTP 429 Too Many Requests must classify as RATE_LIMITED."""
    diag = analyzer.analyze(
        "https://example.com/api",
        status_code=429,
        headers={"Retry-After": "10"},
        body="Rate limit exceeded. Try again in 10 seconds.",
    )

    assert diag.classification == ResponseClassification.RATE_LIMITED
    assert diag.http_status == 429
    assert diag.retryable is True
    assert diag.suggested_action == "backoff_retry"


def test_classify_rate_limited_503_with_retry_after(analyzer: ResponseAnalyzer):
    """HTTP 503 accompanied by Retry-After header indicates temporary rate limiting."""
    diag = analyzer.analyze(
        "https://example.com/api",
        status_code=503,
        headers={"Retry-After": "60"},
        body="Server temporarily overwhelmed.",
    )

    assert diag.classification == ResponseClassification.RATE_LIMITED
    assert diag.retryable is True


# ==============================================================================
# 5. Robots.txt and Auth Required Tests
# ==============================================================================

def test_classify_robots_denied(analyzer: ResponseAnalyzer):
    """Explicitly disallowed URL by robots.txt must classify as ROBOTS_DENIED."""
    diag = analyzer.analyze("https://example.com/admin", is_robots_disallowed=True)

    assert diag.classification == ResponseClassification.ROBOTS_DENIED
    assert diag.suggested_action == "respect_robots"
    assert diag.retryable is False


def test_classify_auth_required_401(analyzer: ResponseAnalyzer):
    """HTTP 401 or 403 with WWW-Authenticate header must classify as AUTH_REQUIRED."""
    diag1 = analyzer.analyze("https://example.com/profile", status_code=401)
    assert diag1.classification == ResponseClassification.AUTH_REQUIRED
    assert diag1.suggested_action == "provide_credentials"

    diag2 = analyzer.analyze(
        "https://example.com/secure",
        status_code=403,
        headers={"WWW-Authenticate": 'Basic realm="User Visible Realm"'},
    )
    assert diag2.classification == ResponseClassification.AUTH_REQUIRED


# ==============================================================================
# 6. JavaScript Rendering & Client-Side SPA Tests
# ==============================================================================

def test_classify_js_render_required_noscript(analyzer: ResponseAnalyzer):
    """Pages explicitly declaring JavaScript is required via <noscript> must trigger JS_RENDER_REQUIRED."""
    html = """
    <!DOCTYPE html>
    <html>
    <head><title>App Portal</title></head>
    <body>
        <noscript>You need to enable JavaScript to run this app.</noscript>
        <div id="root"></div>
    </body>
    </html>
    """
    diag = analyzer.analyze("https://example.com/app", status_code=200, body=html)

    assert diag.classification == ResponseClassification.JS_RENDER_REQUIRED
    assert diag.suggested_action == "render_browser"


def test_classify_js_render_required_empty_spa_container(analyzer: ResponseAnalyzer):
    """Empty SPA mount container with negligible static text must classify as JS_RENDER_REQUIRED."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>SPA Dashboard</title>
        <script src="/static/bundle.js"></script>
    </head>
    <body>
        <div id="app"></div>
    </body>
    </html>
    """
    diag = analyzer.analyze("https://example.com/dashboard", status_code=200, body=html)

    assert diag.classification == ResponseClassification.JS_RENDER_REQUIRED
    assert diag.suggested_action == "render_browser"


# ==============================================================================
# 7. Exceptions, Network and Server Error Tests
# ==============================================================================

def test_classify_network_and_timeout_exceptions(analyzer: ResponseAnalyzer):
    """TimeoutException and NetworkError must map to TIMEOUT and NETWORK_ERROR."""
    diag_timeout = analyzer.analyze("https://example.com", exception=httpx.ReadTimeout("read timed out"))
    assert diag_timeout.classification == ResponseClassification.TIMEOUT
    assert diag_timeout.retryable is True
    assert diag_timeout.suggested_action == "retry_with_longer_timeout"

    diag_net = analyzer.analyze("https://example.com", exception=httpx.ConnectError("Connection refused"))
    assert diag_net.classification == ResponseClassification.NETWORK_ERROR
    assert diag_net.retryable is True


def test_classify_server_error_500(analyzer: ResponseAnalyzer):
    """Standard HTTP 500 without rate limit indicators must classify as SERVER_ERROR."""
    diag = analyzer.analyze("https://example.com/crash", status_code=500, body="500 Internal Server Error")

    assert diag.classification == ResponseClassification.SERVER_ERROR
    assert diag.http_status == 500
    assert diag.retryable is True
    assert diag.suggested_action == "retry_server"


# ==============================================================================
# 8. Diagnostics Privacy & Header Sanitization Tests
# ==============================================================================

def test_diagnostics_sanitizes_sensitive_headers():
    """RequestDiagnostics must strip cookies, auth tokens, and API keys."""
    raw_headers = {
        "Authorization": "Bearer sk-super-secret-token-12345",
        "Cookie": "session_id=abcdef123456; user=admin",
        "Set-Cookie": "session_id=newvalue; HttpOnly",
        "X-API-Key": "my-secret-api-key",
        "User-Agent": "Crawlbot/1.0",
        "Content-Type": "text/html; charset=utf-8",
    }

    sanitized = sanitize_headers(raw_headers)

    assert "User-Agent" in sanitized
    assert "Content-Type" in sanitized
    assert "Authorization" not in sanitized
    assert "Cookie" not in sanitized
    assert "Set-Cookie" not in sanitized
    assert "X-API-Key" not in sanitized


def test_diagnostics_to_dict_serialization():
    """to_dict() must return a clean, JSON-serializable dictionary."""
    diag = RequestDiagnostics(
        url="https://example.com/page",
        domain="example.com",
        classification=ResponseClassification.SUCCESS,
        http_status=200,
        retryable=False,
        suggested_action="proceed",
        reason="Success",
        execution_time_ms=124.5678,
        attempt_count=1,
    )

    data = diag.to_dict()
    assert data["classification"] == "SUCCESS"
    assert data["http_status"] == 200
    assert data["execution_time_ms"] == 124.57
    assert "timestamp" in data
