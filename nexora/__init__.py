"""Nexora Python SDK - Developer Platform for Web Crawling and RAG Pipeline Automation."""

from __future__ import annotations

from nexora.client import CrawlbotClient, NexoraClient
from nexora.exceptions import (
    CrawlbotAPIError,
    CrawlbotAuthenticationError,
    CrawlbotError,
    CrawlbotNotFoundError,
    CrawlbotTimeoutError,
    NexoraAPIError,
    NexoraAuthenticationError,
    NexoraError,
    NexoraNotFoundError,
    NexoraTimeoutError,
)
from nexora.models import (
    ChunkInfo,
    DiscoveredDynamicFieldInfo,
    DynamicFieldDetectionResult,
    ExtractionResult,
    JobInfo,
    LiveChangeEvent,
    LiveWatcherInfo,
    QualityReport,
    SearchResult,
    SyncReport,
)

__version__ = "4.0.0"
__all__ = [
    # Primary Nexora exports
    "NexoraClient",
    "NexoraError",
    "NexoraAPIError",
    "NexoraAuthenticationError",
    "NexoraNotFoundError",
    "NexoraTimeoutError",
    "JobInfo",
    "ExtractionResult",
    "ChunkInfo",
    "SearchResult",
    "QualityReport",
    "SyncReport",
    "LiveWatcherInfo",
    "LiveChangeEvent",
    "DiscoveredDynamicFieldInfo",
    "DynamicFieldDetectionResult",
    "__version__",
    # Backward compatibility exports
    "CrawlbotClient",
    "CrawlbotError",
    "CrawlbotAPIError",
    "CrawlbotAuthenticationError",
    "CrawlbotNotFoundError",
    "CrawlbotTimeoutError",
]
