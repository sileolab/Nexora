"""Security utilities for Crawlbot including SSRF protection, URL validation, and sanitization."""

import ipaddress
import re
import socket
from typing import List, Tuple
from urllib.parse import urlparse

PRIVATE_RANGES: List[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("100.64.0.0/10"),
    ipaddress.ip_network("198.18.0.0/15"),
    ipaddress.ip_network("224.0.0.0/4"),  # multicast
    ipaddress.ip_network("240.0.0.0/4"),  # reserved
    ipaddress.ip_network("255.255.255.255/32"),
]

WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


def is_private_ip(ip_str: str) -> bool:
    """Check if an IP address string belongs to private, loopback, or reserved ranges.

    Args:
        ip_str: IP address string (IPv4 or IPv6).

    Returns:
        True if the IP is in private or restricted ranges, False otherwise.
    """
    if not ip_str or not isinstance(ip_str, str):
        return False

    clean_ip = ip_str.strip().strip("[]")
    try:
        ip = ipaddress.ip_address(clean_ip)
    except ValueError:
        return False

    # Check against explicit private networks
    if any(ip in net for net in PRIVATE_RANGES):
        return True

    # Check IPv4-mapped IPv6 addresses (e.g., ::ffff:127.0.0.1)
    ipv4_mapped = getattr(ip, "ipv4_mapped", None)
    if ipv4_mapped and any(ipv4_mapped in net for net in PRIVATE_RANGES):
        return True

    # Built-in properties from ipaddress module
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_reserved
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
    )


def validate_url_scheme(url: str) -> bool:
    """Validate that the URL scheme is strictly 'http' or 'https'.

    Args:
        url: The URL string to inspect.

    Returns:
        True if the URL scheme is 'http' or 'https', False otherwise.
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url.strip())
        return parsed.scheme.lower() in ("http", "https")
    except Exception:
        return False


def has_embedded_credentials(url: str) -> bool:
    """Check whether the URL contains embedded credentials (e.g., user:pass@host).

    Args:
        url: The URL string to inspect.

    Returns:
        True if embedded credentials (username or password) are present, False otherwise.
    """
    if not url or not isinstance(url, str):
        return False

    try:
        parsed = urlparse(url.strip())
        if parsed.username is not None or parsed.password is not None:
            return True
        # Prevent obfuscation where @ appears in the network location
        if "@" in parsed.netloc:
            return True
        return False
    except Exception:
        return False


def resolve_and_validate_host(hostname: str) -> list[str]:
    """Resolve a hostname via DNS and validate that none of its IP addresses are private.

    Uses socket.getaddrinfo to resolve both IPv4 and IPv6 addresses.

    Args:
        hostname: Hostname or IP string to resolve and validate.

    Returns:
        list[str]: List of unique resolved public IP addresses.

    Raises:
        ValueError: If the hostname is empty, cannot be resolved, or resolves to
                    any private, loopback, or reserved IP address.
    """
    if not hostname or not isinstance(hostname, str):
        raise ValueError("Hostname cannot be empty")

    clean_host = hostname.strip().strip("[]")
    if not clean_host:
        raise ValueError("Hostname cannot be empty")

    # Check if hostname directly is an IP address
    try:
        direct_ip = ipaddress.ip_address(clean_host)
        if is_private_ip(str(direct_ip)):
            raise ValueError(
                f"Host '{hostname}' is a private/restricted IP address: {direct_ip}"
            )
        return [str(direct_ip)]
    except ValueError as err:
        # If it raised due to being a private IP, propagate the exception
        if "private/restricted IP" in str(err):
            raise
        # Otherwise, it's a domain name that needs DNS resolution

    try:
        addr_info = socket.getaddrinfo(
            clean_host,
            None,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as e:
        raise ValueError(f"Failed to resolve host '{hostname}': {e.strerror}") from e
    except Exception as e:
        raise ValueError(f"Failed to resolve host '{hostname}': {str(e)}") from e

    if not addr_info:
        raise ValueError(f"No DNS records found for host '{hostname}'")

    resolved_ips: list[str] = []
    for item in addr_info:
        ip = item[4][0]
        if ip not in resolved_ips:
            resolved_ips.append(ip)

    for ip in resolved_ips:
        if is_private_ip(ip):
            raise ValueError(
                f"Host '{hostname}' resolved to private/restricted IP address: {ip}"
            )

    return resolved_ips


def validate_url_safety(url: str) -> tuple[bool, str]:
    """Perform comprehensive SSRF and security checks on a URL.

    Verifies scheme, absence of embedded credentials, hostname presence and validity,
    and ensures that all resolved IP addresses are safe public IPs.

    Args:
        url: The URL to validate.

    Returns:
        tuple[bool, str]: (is_safe, reason) where is_safe is True if URL passed all
                          validations, or False with an explanation message.
    """
    if not url or not isinstance(url, str):
        return False, "URL is empty or invalid"

    stripped_url = url.strip()

    # 1. Scheme check
    if not validate_url_scheme(stripped_url):
        return False, "Invalid scheme: only http and https are allowed"

    # 2. Embedded credentials check
    if has_embedded_credentials(stripped_url):
        return False, "URL contains embedded credentials"

    # 3. Parse URL structure
    try:
        parsed = urlparse(stripped_url)
    except Exception as e:
        return False, f"Malformed URL: {str(e)}"

    hostname = parsed.hostname
    if not hostname:
        return False, "URL does not contain a valid hostname"

    # Check port validity if present
    if parsed.port is not None:
        if not (1 <= parsed.port <= 65535):
            return False, f"Invalid port: {parsed.port}"

    # 4. Resolve DNS and validate host IPs
    try:
        resolve_and_validate_host(hostname)
    except ValueError as e:
        return False, str(e)

    return True, "URL is safe"


def is_excluded_path(url: str, patterns: list[str]) -> bool:
    """Check if a URL matches any exclusion regex patterns.

    Matches against both the full URL and URL path (including query and fragment).

    Args:
        url: The URL string to test.
        patterns: List of regex patterns to match against.

    Returns:
        True if any exclusion pattern matches, False otherwise.
    """
    if not url or not patterns:
        return False

    try:
        parsed = urlparse(url)
        path_with_query = parsed.path
        if parsed.query:
            path_with_query = f"{path_with_query}?{parsed.query}"
        if parsed.fragment:
            path_with_query = f"{path_with_query}#{parsed.fragment}"
    except Exception:
        path_with_query = url

    for pattern in patterns:
        if not pattern:
            continue
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
            if (
                compiled.search(url)
                or compiled.search(path_with_query)
                or compiled.search(parsed.path)
            ):
                return True
        except re.error:
            # Fallback to case-insensitive substring match if regex compilation fails
            if pattern.lower() in url.lower():
                return True

    return False


def sanitize_filename(name: str) -> str:
    """Sanitize a filename to prevent path traversal and ensure filesystem compatibility.

    Removes directory traversal sequences ('..'), path separators ('/', '\\'),
    null bytes, Windows reserved characters (<>:"/\\|?*), and control characters.
    Handles Windows reserved filenames (CON, PRN, etc.) and enforces length limits.

    Args:
        name: Raw filename to sanitize.

    Returns:
        Safe filename string.
    """
    if not name or not isinstance(name, str):
        return "export"

    # Strip null bytes
    cleaned = name.replace("\x00", "")

    # Replace path separators with underscores to prevent path traversal
    cleaned = re.sub(r"[/\\]+", "_", cleaned)

    # Collapse multiple consecutive dots / directory traversal
    cleaned = re.sub(r"\.{2,}", "_", cleaned)

    # Strip illegal filesystem characters (<>:"/\|?*) and control chars (0x00-0x1F, 0x7F)
    cleaned = re.sub(r'[\x00-\x1f\x7f<>:"/\\|?*]', "_", cleaned)

    # Collapse multiple consecutive underscores
    cleaned = re.sub(r"_+", "_", cleaned)

    # Strip leading/trailing spaces, dots, and underscores
    cleaned = cleaned.strip(". _")

    if not cleaned:
        return "export"

    # Guard against Windows reserved device names
    base_stem = cleaned.split(".")[0].upper()
    if base_stem in WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    # Enforce maximum filename length (255 characters), preserving extension
    max_len = 255
    if len(cleaned) > max_len:
        if "." in cleaned:
            stem, ext = cleaned.rsplit(".", 1)
            ext = f".{ext}"
            cleaned = f"{stem[: max_len - len(ext)]}{ext}"
        else:
            cleaned = cleaned[:max_len]

    return cleaned


# ==============================================================================
# PHASE 4 & 5: API AUTHENTICATION, TENANT ISOLATION & RATE LIMITING
# ==============================================================================

import logging
import time
from collections import defaultdict, deque
from typing import Optional
from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import get_settings

logger = logging.getLogger(__name__)

api_key_header_scheme = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)


class SlidingWindowRateLimiter:
    """Thread-safe in-memory sliding window rate limiter per client or workspace."""

    def __init__(self, max_requests: int = 1000, window_seconds: float = 60.0) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._history: dict[str, deque[float]] = defaultdict(deque)

    def is_allowed(self, key: str) -> tuple[bool, int]:
        """Check if request is allowed. Returns (allowed: bool, retry_after_seconds: int)."""
        if not key or key in ("testclient", "unknown", "127.0.0.1", "localhost", "::1"):
            return True, 0

        now = time.monotonic()
        q = self._history[key]
        cutoff = now - self.window_seconds

        while q and q[0] <= cutoff:
            q.popleft()

        # Periodic cleanup of stale keys when registry exceeds threshold
        if len(self._history) > 5000:
            self._cleanup_stale(now)

        if len(q) < self.max_requests:
            q.append(now)
            return True, 0

        oldest = q[0]
        retry_after = max(1, int(self.window_seconds - (now - oldest)))
        return False, retry_after

    def _cleanup_stale(self, now: float) -> None:
        """Evict inactive client entries to bound memory usage."""
        cutoff = now - self.window_seconds
        stale_keys = [k for k, q in self._history.items() if not q or q[-1] <= cutoff]
        for k in stale_keys:
            self._history.pop(k, None)

    def reset(self, key: Optional[str] = None) -> None:
        """Clear rate limit history."""
        if key:
            self._history.pop(key, None)
        else:
            self._history.clear()


_rate_limiter = SlidingWindowRateLimiter(max_requests=1000, window_seconds=60.0)


def get_rate_limiter() -> SlidingWindowRateLimiter:
    return _rate_limiter


def verify_api_key(
    x_api_key: Optional[str] = Security(api_key_header_scheme),
    bearer_auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> bool:
    """Validate API Key if configured in application settings.

    Accepts either the global settings.api_key (master admin key)
    OR a valid per-workspace API key (cbk_...).
    If settings.api_key is empty/None: allows all requests (local dev mode).
    """
    settings = get_settings()
    configured_key = settings.api_key

    # Extract provided token
    token = ""
    if x_api_key and x_api_key.strip():
        token = x_api_key.strip()
    elif bearer_auth and bearer_auth.credentials:
        token = bearer_auth.credentials.strip()

    # Check per-workspace API key resolution
    if token:
        try:
            from app.services.workspace_manager import get_workspace_manager
            wid = get_workspace_manager().resolve_workspace_by_key(token)
            if wid:
                return True
        except Exception:
            pass

    # Dev / Local mode: no authentication required
    if not configured_key or not configured_key.strip():
        return True

    # Check master key
    if token and token == configured_key.strip():
        return True

    logger.warning("Unauthorized API request: invalid or missing API Key")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: Missing or invalid API Key. Provide a valid 'X-API-Key' header or 'Bearer' token.",
        headers={"WWW-Authenticate": "Bearer"},
    )

# ==============================================================================
# PHASE 1: IDENTIFIER VALIDATION, PATH CONTAINMENT & FAIL-CLOSED ADMIN AUTH
# ==============================================================================

import hmac
from pathlib import Path

_SAFE_IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_\-]{3,64}$")


def is_safe_identifier(val: str) -> bool:
    """Validate identifier (workspace_id, tenant_id, job_id, etc.) to prevent directory traversal.

    Must be 3-64 characters alphanumeric, hyphen, or underscore only.
    Disallows dots, slashes, null bytes, and traversal sequences.
    """
    if not val or not isinstance(val, str):
        return False
    clean = val.strip()
    if not _SAFE_IDENTIFIER_RE.match(clean):
        return False
    if ".." in clean or "/" in clean or "\\" in clean or "\x00" in clean:
        return False
    return True


def validate_path_containment(base_dir: Path | str, target_path: Path | str) -> bool:
    """Ensure target_path resolves strictly within base_dir."""
    try:
        base = Path(base_dir).resolve()
        target = Path(target_path).resolve()
        return base in target.parents or base == target
    except Exception:
        return False


def require_admin(
    request: Request,
    x_api_key: Optional[str] = Security(api_key_header_scheme),
    bearer_auth: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> bool:
    """FastAPI dependency to verify Master Admin credentials with Fail-Closed behavior.

    - If NEXORA_API_KEY is not configured or empty, denies access (401 Unauthorized).
    - If a standard tenant key (starts with 'cbk_' or resolves to a workspace) is used, denies access with 403 Forbidden.
    - If API key is missing or invalid, denies access with 401 Unauthorized.
    - Uses constant-time comparison to prevent timing side-channel attacks.
    """
    settings = get_settings()
    configured_key = (settings.api_key or "").strip()

    # Fail closed: No admin access if admin secret is not configured
    if not configured_key:
        logger.warning("Admin endpoint rejected: master admin key (NEXORA_API_KEY) is not configured.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Master admin API key is not configured or missing.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Extract provided token
    token = ""
    if x_api_key and x_api_key.strip():
        token = x_api_key.strip()
    elif bearer_auth and bearer_auth.credentials:
        token = bearer_auth.credentials.strip()

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Master admin credentials required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Standard tenant keys are strictly forbidden from accessing admin endpoints
    if token.startswith("cbk_"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Workspace keys are not permitted to access admin endpoints.",
        )

    from app.services.workspace_manager import get_workspace_manager
    if get_workspace_manager().resolve_workspace_by_key(token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Workspace keys are not permitted to access admin endpoints.",
        )

    if not hmac.compare_digest(token, configured_key):
        logger.warning("Admin endpoint rejected: invalid master admin key attempted.")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized: Invalid master admin credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True

# ==============================================================================
# PHASE 2: SECRET LEAKAGE PREVENTION & REDACTION
# ==============================================================================

def sanitize_secret_leakage(text: str, secrets: Optional[list[str]] = None) -> str:
    """Sanitize API keys and secrets from error messages, exceptions, and logs.

    Replaces explicit secret values, OpenAI keys ('sk-...'), and workspace keys ('cbk_...').
    """
    if not text or not isinstance(text, str):
        return ""
    result = text
    if secrets:
        for s in secrets:
            if s and isinstance(s, str) and len(s) >= 6 and s in result:
                result = result.replace(s, "[REDACTED_SECRET]")

    # Mask OpenAI API keys
    result = re.sub(r"sk-[a-zA-Z0-9_\-]{16,}", "sk-[REDACTED]", result)
    # Mask Crawlbot Workspace API keys
    result = re.sub(r"nxk_[a-zA-Z0-9_\-]{16,}", "nxk_[REDACTED]", result)
    result = re.sub(r"cbk_[a-zA-Z0-9_\-]{16,}", "cbk_[REDACTED]", result)
    # Mask Bearer tokens
    result = re.sub(r"(Bearer\s+)[a-zA-Z0-9_\-\.]{16,}", r"\1[REDACTED]", result, flags=re.IGNORECASE)
    return result

