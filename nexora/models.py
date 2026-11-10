"""Typed data models for Nexora Python SDK."""

from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, ConfigDict, Field


class JobInfo(BaseModel):
    """Metadata and execution state for a background Nexora job."""

    model_config = ConfigDict(extra="ignore")

    job_id: str
    job_type: str = "crawl"
    state: str = "pending"
    created_at: str = ""
    updated_at: str = ""
    start_url: Optional[str] = None
    urls_discovered: int = 0
    urls_crawled: int = 0
    error: Optional[str] = None
    documents_count: int = 0
    chunks_count: int = 0
    total_urls: int = 0
    pages: list[Any] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    """Cleaned structured output for a single extracted document."""

    model_config = ConfigDict(extra="ignore")

    url: str
    title: str = ""
    text: str = ""
    markdown: str = ""
    html_cleaned: str = ""
    word_count: int = 0
    char_count: int = 0
    content_hash: str = ""
    language: str = "en"
    page_type: str = "article"
    quality_score: float = 0.0
    status: str = "success"


class ChunkInfo(BaseModel):
    """Single semantic chunk generated from a document."""

    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    source_url: str
    chunk_index: int
    total_chunks: int
    text: str
    heading_context: Optional[str] = None
    word_count: int = 0
    has_embedding: bool = False


class SearchResult(BaseModel):
    """Retrieval search hit matching a query."""

    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    source_url: str
    title: str = ""
    text: str = ""
    score: float
    raw_score: Optional[float] = None
    normalized_score: Optional[float] = None
    method: str = "hybrid"
    heading_context: Optional[str] = None
    category: Optional[str] = None


class QualityReport(BaseModel):
    """Quality and readiness score report for an extracted dataset."""

    model_config = ConfigDict(extra="ignore")

    job_id: str
    total_documents: int
    overall_score: float
    passed: bool
    metrics: dict[str, Any] = Field(default_factory=dict)
    recommendations: list[str] = Field(default_factory=list)


class SyncReport(BaseModel):
    """Summary of an incremental synchronization run."""

    model_config = ConfigDict(extra="ignore")

    project_id: str
    total_candidates: int
    new_urls: list[str] = Field(default_factory=list)
    modified_urls: list[str] = Field(default_factory=list)
    unchanged_urls: list[str] = Field(default_factory=list)
    deleted_urls: list[str] = Field(default_factory=list)
    config_invalidated: bool = False
    reused_chunks: int = 0
    reused_embeddings: int = 0
    reprocessed_chunks: int = 0
    status: str = "completed"
