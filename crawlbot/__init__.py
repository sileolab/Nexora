"""Crawlbot Python SDK (Compatibility Layer - Powered by Nexora)."""

from __future__ import annotations

from nexora import (
    ChunkInfo,
    CrawlbotAPIError,
    CrawlbotAuthenticationError,
    CrawlbotClient,
    CrawlbotError,
    CrawlbotNotFoundError,
    CrawlbotTimeoutError,
    ExtractionResult,
    JobInfo,
    NexoraAPIError,
    NexoraAuthenticationError,
    NexoraClient,
    NexoraError,
    NexoraNotFoundError,
    NexoraTimeoutError,
    QualityReport,
    SearchResult,
    SyncReport,
    __version__,
)

__all__ = [
    "CrawlbotClient",
    "CrawlbotError",
    "CrawlbotAPIError",
    "CrawlbotAuthenticationError",
    "CrawlbotNotFoundError",
    "CrawlbotTimeoutError",
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
    "__version__",
]
